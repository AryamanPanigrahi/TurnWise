"""Optional trace recorder for the founders' own test drives (development only).

OFF by default. The normal server stores no raw GPS (DPDP, CLAUDE.md rule 5). When
`TURNWISE_RECORD_DIR` is set, every trip is also written to that folder so a field
test becomes a replayable case for `python -m engine.harness`:

    <trip_id>.jsonl          the GPS fixes, exactly the POST /v1/gps point shape
    <trip_id>.route.json     the planned route bundle (what the engine was following)
    <trip_id>.events.jsonl   what the engine said live (to compare with what you saw)

To turn one into a test: copy the three files into traces/ under a proper name
(see traces/README.md), write the `.expected.json` by hand from your notes, and trim
the ends so home/office locations do not land in git. Record only people who agreed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

FIX_FIELDS = ("trip_id", "ts", "lat", "lon", "speed", "heading", "accuracy")


class TraceRecorder:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _append(self, name: str, obj: Mapping) -> None:
        with (self.dir / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def start(self, trip_id: str, bundle: Mapping) -> None:
        (self.dir / f"{trip_id}.route.json").write_text(json.dumps(bundle) + "\n", encoding="utf-8")

    def fix(self, trip_id: str, fix: Mapping) -> None:
        self._append(f"{trip_id}.jsonl", {k: fix.get(k) for k in FIX_FIELDS})

    def event(self, trip_id: str, message: Mapping) -> None:
        self._append(f"{trip_id}.events.jsonl", message)
