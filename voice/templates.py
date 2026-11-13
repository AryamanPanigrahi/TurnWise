"""Load and validate per-language templates from voice/templates/<lang>.yaml."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

TEMPLATES_DIR = Path(__file__).parent / "templates"

INTENTS = ("am_i_wrong", "which_branch", "left_or_right", "distance_to_next", "eta", "repeat")
REQUIRED_ANSWERS = (
    "which_branch",
    "left_or_right",
    "left_or_right.straight",
    "distance_to_next",
    "am_i_wrong.on_route",
    "am_i_wrong.off_route",
    "eta",
    "not_sure",
    "please_repeat",
)
REQUIRED_ALERTS = ("off_route", "off_route_generic", "back_on_route")
REQUIRED_UNITS = ("m", "km", "min", "hour", "hour_min")


class TemplateError(ValueError):
    """A template file is missing a required key or is malformed."""


@dataclass(frozen=True)
class TemplateSet:
    lang: str
    version: int
    intents: dict[str, list[str]]
    slots: dict[str, dict[str, list[str]]]
    vocab: dict[str, dict[str, str]]
    answers: dict[str, Any]
    alerts: dict[str, str]


def available_languages() -> list[str]:
    return sorted(p.stem for p in TEMPLATES_DIR.glob("*.yaml"))


def _nfc(obj: Any) -> Any:
    """NFC-normalise every string so Indic text compares consistently."""
    if isinstance(obj, str):
        return unicodedata.normalize("NFC", obj)
    if isinstance(obj, list):
        return [_nfc(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _nfc(v) for k, v in obj.items()}
    return obj


def validate(raw: dict[str, Any], source: str) -> None:
    def need(cond: bool, msg: str) -> None:
        if not cond:
            raise TemplateError(f"{source}: {msg}")

    for key in ("lang", "version", "intents", "slots", "vocab", "answers", "alerts"):
        need(key in raw, f"missing top-level key '{key}'")
    for intent in INTENTS:
        need(bool(raw["intents"].get(intent)), f"intent '{intent}' has no keywords")
    for key in REQUIRED_ANSWERS:
        need(key in raw["answers"], f"missing answer '{key}'")
    for key in REQUIRED_ALERTS:
        need(key in raw["alerts"], f"missing alert '{key}'")
    for key in REQUIRED_UNITS:
        need(key in raw["vocab"].get("units", {}), f"missing vocab.units.{key}")
    for section in ("branch", "direction", "maneuver", "recovery"):
        need(section in raw["vocab"], f"missing vocab.{section}")


@lru_cache(maxsize=None)
def load(lang: str) -> TemplateSet:
    path = TEMPLATES_DIR / f"{lang}.yaml"
    if not path.is_file():
        raise TemplateError(f"no templates for language '{lang}' (looked for {path})")
    raw = _nfc(yaml.safe_load(path.read_text(encoding="utf-8")))
    validate(raw, path.name)
    if raw["lang"] != lang:
        raise TemplateError(f"{path.name}: lang is '{raw['lang']}', expected '{lang}'")
    return TemplateSet(
        lang=raw["lang"],
        version=int(raw["version"]),
        intents=raw["intents"],
        slots=raw["slots"],
        vocab=raw["vocab"],
        answers=raw["answers"],
        alerts=raw["alerts"],
    )
