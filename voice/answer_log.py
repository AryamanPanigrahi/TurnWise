"""Structured log of every voice answer (CLAUDE.md: intent, facts, latency, cost).

Raw audio is never stored. The transcript *is* stored, because it is the only
way to debug intent accuracy; it counts as driver personal data, so the same
DPDP retention job as raw GPS must delete it (default 90 days).
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class AnswerRecord:
    ts: str                          # UTC ISO-8601
    trip_id: str
    driver_id: str
    lang: str
    transcript: str
    intent: str
    intent_source: str               # "rules" | "llm" | "none"
    matched: str | None
    answer_key: str
    facts: dict[str, Any]
    template_key: str
    fell_back: bool
    fallback_reason: str | None
    tts_cache_hit: bool | None
    latency_ms: dict[str, float] = field(default_factory=dict)   # per stage + "total"
    cost_inr: dict[str, float] = field(default_factory=dict)     # per service + "total"
    over_budget: bool = False
    error: str | None = None


class AnswerSink(Protocol):
    def write(self, record: AnswerRecord) -> None: ...


class JsonlAnswerLog:
    """Append one JSON object per line. Swap for a DB table once the backend exists."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def write(self, record: AnswerRecord) -> None:
        line = json.dumps(asdict(record), ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class MemoryAnswerLog:
    def __init__(self):
        self.records: list[AnswerRecord] = []

    def write(self, record: AnswerRecord) -> None:
        self.records.append(record)
