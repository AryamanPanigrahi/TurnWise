"""Rule-based intent router for the 6 templated intents.

Pure and deterministic: no network, no AI model. Text that matches nothing
returns intent "unknown", which the pipeline may later send to the Sarvam LLM
fallback (with the strict "answer ONLY from these facts" prompt).

Matching: the utterance and each keyword are tokenised the same way; a keyword
matches when its tokens appear consecutively and each utterance token *starts
with* the keyword token. Prefix matching handles Kannada/Hindi suffixes,
e.g. keyword "ಎಡ" matches "ಎಡಕ್ಕೆ" ("to the left").
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

from voice.templates import load

# Earlier intents win when several match. Rationale:
# - am_i_wrong first: safety question, and "right road" must not become left/right.
# - which_branch before distance: "how far is the flyover" is best answered by
#   the branch answer, which already includes the distance.
# - distance/eta before left_or_right: "how far is the left turn" asks distance;
#   "how much time left" asks ETA.
# - repeat last: "say again, how far?" should answer the real question.
PRIORITY: tuple[str, ...] = (
    "am_i_wrong",
    "which_branch",
    "distance_to_next",
    "eta",
    "left_or_right",
    "repeat",
)

_INVISIBLE = {"‌", "‍", "﻿"}  # ZWNJ, ZWJ, BOM


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).casefold()
    chars = []
    for ch in text:
        if ch in _INVISIBLE:
            continue
        cat = unicodedata.category(ch)
        # Punctuation and symbols (incl. Devanagari danda '।') become spaces.
        chars.append(" " if cat[0] in ("P", "S") else ch)
    return "".join(chars).split()


def _match_at(tokens: Sequence[str], kw: Sequence[str]) -> int:
    """Index of the first match of keyword tokens `kw` in `tokens`, or -1."""
    n = len(kw)
    for i in range(len(tokens) - n + 1):
        if all(tokens[i + j].startswith(kw[j]) for j in range(n)):
            return i
    return -1


@dataclass(frozen=True)
class Intent:
    name: str
    slots: dict = field(default_factory=dict)
    matched: str | None = None  # keyword that triggered the match, for logging


def route(text: str, lang: str) -> Intent:
    ts = load(lang)
    tokens = tokenize(text)
    if not tokens:
        return Intent("unknown")

    for name in PRIORITY:
        for kw in ts.intents.get(name, []):
            if _match_at(tokens, tokenize(kw)) >= 0:
                return Intent(name, _extract_slots(name, tokens, ts.slots), kw)
    return Intent("unknown")


def _extract_slots(intent: str, tokens: list[str], slots: dict) -> dict:
    if intent != "which_branch":
        return {}
    # Options in the order the driver said them, e.g. "flyover or service road?"
    found: list[tuple[int, str]] = []
    for value, keywords in slots.get("branch", {}).items():
        positions = [p for p in (_match_at(tokens, tokenize(k)) for k in keywords) if p >= 0]
        if positions:
            found.append((min(positions), value))
    return {"options": [v for _, v in sorted(found)]} if found else {}
