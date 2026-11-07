"""Replay harness: run recorded (or synthetic) drives through the engine and score them.

    python -m engine.harness                 # every trace in traces/
    python -m engine.harness traces/x.jsonl  # one trace

A *case* is three sibling files in `traces/`:

    <name>.jsonl           GPS fixes, POST /v1/gps shape (Ram's format)
    <name>.expected.json   what the engine should say (Ram's format, plus optional
                           per-event "early_s" / "late_s" tolerances)
    <name>.route.json      the planned route the driver was following:
                           {"source": "valhalla|synthetic|...", "route": [[lat, lon], ...]}

The route file is a saved fixture, so replay tests never call Valhalla and stay
deterministic. For a real drive, save the /route polyline once when recording.

Scoring (CLAUDE.md phase 1): each expected `off_route` must be raised no later
than `late_s` (default 2 s) after its `ts` and no earlier than `early_s`
(default 5 s) before it; any `off_route` the engine raises that no expected event
explains is a FALSE ALARM; a `clean` drive must raise none. `decision_point_ahead`
and `arrived` are listed as skipped until the engine produces them.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from engine.geometry import LatLon
from engine.wrong_way import DetectorConfig, Event, parse_ts, replay

# (early_s, late_s) tolerances per event type; per-event keys in expected.json override.
DEFAULT_TOLERANCE = {
    "off_route": (5.0, 2.0),          # the 2 s rule is the "late" side
    "back_on_route": (10.0, 10.0),    # not a safety budget, so looser
}
NOT_YET_SUPPORTED = {"decision_point_ahead", "arrived"}


@dataclass(frozen=True)
class Case:
    name: str
    rows: list[dict]
    expected: dict
    route: list[LatLon]


@dataclass
class CaseResult:
    name: str
    problems: list[str] = field(default_factory=list)
    latencies: list[tuple[str, float]] = field(default_factory=list)  # (event, detector ts - expected ts)
    skipped: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


# -- loading ---------------------------------------------------------------------
def route_path(jsonl: Path) -> Path:
    return jsonl.with_name(jsonl.name.removesuffix(".jsonl") + ".route.json")


def expected_path(jsonl: Path) -> Path:
    return jsonl.with_name(jsonl.name.removesuffix(".jsonl") + ".expected.json")


def write_route(jsonl: Path, route: Sequence[LatLon], source: str) -> None:
    data = {"source": source, "route": [[round(a, 6), round(b, 6)] for a, b in route]}
    route_path(jsonl).write_text(json.dumps(data) + "\n", encoding="utf-8")


def load_case(jsonl: Path) -> Case:
    """Load a case. Raises FileNotFoundError naming the missing sibling file."""
    exp, rte = expected_path(jsonl), route_path(jsonl)
    for p in (exp, rte):
        if not p.exists():
            raise FileNotFoundError(p.name)
    rows = [json.loads(line) for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    route = [(float(a), float(b)) for a, b in json.loads(rte.read_text(encoding="utf-8"))["route"]]
    return Case(jsonl.name.removesuffix(".jsonl"), rows,
                json.loads(exp.read_text(encoding="utf-8")), route)


# -- scoring ---------------------------------------------------------------------
def score(name: str, expected: dict, events: Sequence[Event]) -> CaseResult:
    """Compare the engine's events with a case's expected events."""
    res = CaseResult(name)
    unused = list(events)

    for exp_ev in expected.get("events", []):
        kind = exp_ev["event"]
        if kind in NOT_YET_SUPPORTED:
            res.skipped.append(f"{kind} at {exp_ev['ts']}")
            continue
        early_default, late_default = DEFAULT_TOLERANCE.get(kind, (5.0, 2.0))
        early = float(exp_ev.get("early_s", early_default))
        late = float(exp_ev.get("late_s", late_default))
        t_exp = parse_ts(exp_ev["ts"])

        match = next((e for e in unused
                      if e.event == kind and -early <= parse_ts(e.ts) - t_exp <= late), None)
        if match is None:
            seen = [f"{e.event}@{parse_ts(e.ts) - t_exp:+.1f}s" for e in unused if e.event == kind]
            res.problems.append(
                f"MISSED {kind} expected at {exp_ev['ts']} (window -{early:g}s..+{late:g}s)"
                + (f"; engine raised {', '.join(seen)}" if seen else "; engine raised none"))
            continue
        unused.remove(match)
        res.latencies.append((kind, parse_ts(match.ts) - t_exp))

    for e in unused:
        label = "FALSE ALARM" if e.event == "off_route" else "UNEXPECTED"
        res.problems.append(f"{label}: {e.event} at {e.ts}")

    if expected.get("clean") and any(e.event == "off_route" for e in events):
        res.problems.append("clean drive must raise zero off_route events")
    return res


def run_case(case: Case, config: DetectorConfig | None = None) -> CaseResult:
    return score(case.name, case.expected, replay(case.route, case.rows, config))


def run_dir(directory: Path, config: DetectorConfig | None = None
            ) -> tuple[list[CaseResult], list[str]]:
    """Run every trace in a directory. Returns (results, names without a route file)."""
    results, unrouted = [], []
    for jsonl in sorted(directory.glob("*.jsonl")):
        try:
            results.append(run_case(load_case(jsonl), config))
        except FileNotFoundError as missing:
            unrouted.append(f"{jsonl.name} (missing {missing})")
    return results, unrouted


def format_report(results: Sequence[CaseResult], unrouted: Sequence[str] = ()) -> str:
    lines = []
    for r in results:
        lat = ", ".join(f"{k} {v:+.1f}s" for k, v in r.latencies)
        lines.append(f"{'PASS' if r.passed else 'FAIL'}  {r.name}" + (f"  [{lat}]" if lat else ""))
        lines += [f"      {p}" for p in r.problems]
        lines += [f"      skipped (engine can't produce it yet): {s}" for s in r.skipped]
    for u in unrouted:
        lines.append(f"SKIP  {u}")
    passed = sum(r.passed for r in results)
    lines.append(f"\n{passed}/{len(results)} traces passed" + (f", {len(unrouted)} skipped" if unrouted else ""))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path, help="trace .jsonl files (default: all in traces/)")
    a = ap.parse_args(argv)

    if a.paths:
        results, unrouted = [], []
        for p in a.paths:
            try:
                results.append(run_case(load_case(p)))
            except FileNotFoundError as missing:
                unrouted.append(f"{p.name} (missing {missing})")
    else:
        results, unrouted = run_dir(Path("traces"))
    print(format_report(results, unrouted))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
