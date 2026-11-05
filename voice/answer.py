"""Render engine facts into a spoken sentence using voice/templates/<lang>.yaml.

Safety rules (CLAUDE.md #1, #2):
- This module only phrases facts. It never invents a direction or distance.
- If any fact a template needs is missing, invalid, contradictory or
  low-confidence, the answer is the "not_sure" template
  ("I'm not sure, follow the screen") — never a guess.
- Wrong-way alerts are rendered here from templates only; no AI model.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from voice.templates import TemplateSet, load
from voice.units import format_distance, format_duration

MIN_CONFIDENCE = 0.6


@dataclass(frozen=True)
class Rendered:
    text: str
    template_key: str      # which template was used, for the answer log
    fell_back: bool        # True when we answered "not_sure" instead of the asked key
    reason: str | None = None


class _MissingFact(Exception):
    pass


def _fields(text: str) -> list[str]:
    return [f for _, f, _, _ in string.Formatter().parse(text) if f]


def _resolvers(ts: TemplateSet, facts: Mapping[str, Any], choice: str) -> dict[str, Callable[[], str]]:
    units = ts.vocab["units"]

    def num(key: str) -> float:
        v = facts.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise _MissingFact(key)
        return float(v)

    def vocab(section: str, key: Any) -> str:
        try:
            return ts.vocab[section][key]
        except (KeyError, TypeError):
            raise _MissingFact(f"{section}:{key}") from None

    def landmark() -> str:
        v = facts.get("landmark")
        if not isinstance(v, str) or not v.strip():
            raise _MissingFact("landmark")
        return v.strip()

    return {
        "distance": lambda: format_distance(num("distance_m"), units),
        "remaining": lambda: format_distance(num("remaining_m"), units),
        "eta": lambda: format_duration(num("eta_s"), units),
        "branch": lambda: vocab("branch", facts.get("on_route") or choice),
        "direction": lambda: vocab("direction", choice),
        "maneuver": lambda: vocab("maneuver", facts.get("maneuver")),
        "recovery": lambda: vocab("recovery", facts.get("recovery_action")),
        "landmark": landmark,
    }


def _fill(ts: TemplateSet, text: str, facts: Mapping[str, Any], choice: str) -> str:
    resolve = _resolvers(ts, facts, choice)
    values = {}
    for f in _fields(text):
        if f not in resolve:
            raise _MissingFact(f)
        values[f] = resolve[f]()
    return text.format(**values)


def _not_sure(ts: TemplateSet, reason: str) -> Rendered:
    return Rendered(ts.answers["not_sure"], "not_sure", fell_back=True, reason=reason)


def render_answer(lang: str, answer_key: str, facts: Mapping[str, Any] | None = None) -> Rendered:
    """Render a POST /v1/ask response ({answer_key, facts}) as a sentence."""
    ts = load(lang)
    facts = facts or {}
    base, _, choice = answer_key.partition(".")

    if answer_key == "not_sure":
        return Rendered(ts.answers["not_sure"], "not_sure", fell_back=False)

    conf = facts.get("confidence")
    if conf is not None and (not isinstance(conf, (int, float)) or conf < MIN_CONFIDENCE):
        return _not_sure(ts, f"low confidence: {conf}")

    # The branch named in the key and in the facts must agree.
    on_route = facts.get("on_route")
    if base == "which_branch" and choice and on_route and on_route != choice:
        return _not_sure(ts, f"answer_key says {choice}, facts say {on_route}")

    key = answer_key if answer_key in ts.answers else base
    template = ts.answers.get(key)
    if template is None:
        return _not_sure(ts, f"no template for '{answer_key}'")

    if isinstance(template, dict):
        candidates = [template["with_landmark"]] if facts.get("landmark") and "with_landmark" in template else []
        candidates.append(template["default"])
    else:
        candidates = [template]

    last_missing = None
    for text in candidates:  # with_landmark first, then plain default
        try:
            return Rendered(_fill(ts, text, facts, choice), key, fell_back=False)
        except _MissingFact as e:
            last_missing = str(e)
    return _not_sure(ts, f"missing fact: {last_missing}")


def render_alert(lang: str, event: str, data: Mapping[str, Any] | None = None) -> Rendered:
    """Render a WS trip event (off_route, back_on_route) as a templated alert.

    An off_route alert is always spoken: if the recovery details are missing we
    still warn the driver with the generic "Wrong way! Follow the screen."
    """
    ts = load(lang)
    data = data or {}
    if event == "back_on_route":
        return Rendered(ts.alerts["back_on_route"], "back_on_route", fell_back=False)
    if event != "off_route":
        raise ValueError(f"no alert template for event '{event}'")

    recovery = data.get("recovery") or {}
    facts = {"distance_m": recovery.get("distance_m"), "recovery_action": recovery.get("action")}
    try:
        return Rendered(_fill(ts, ts.alerts["off_route"], facts, ""), "off_route", fell_back=False)
    except _MissingFact as e:
        return Rendered(ts.alerts["off_route_generic"], "off_route_generic", fell_back=True,
                        reason=f"missing fact: {e}")
