"""Check traces against the gps contract and their `.expected.json` files.

    python -m tools.trace_check                 # every trace in traces/
    python -m tools.trace_check traces/x.jsonl  # one trace

Exit code 1 if any trace has errors. Warnings (gaps, glitches) don't fail.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.trace_format import check_expected, check_points, loads_jsonl


def check_file(path: Path) -> tuple[list[str], list[str], str]:
    rows = loads_jsonl(path.read_text(encoding="utf-8"))
    r = check_points(rows)
    errors = list(r.errors)
    exp = path.with_suffix(".expected.json")
    if not exp.exists():
        errors.append(f"missing {exp.name}")
    else:
        errors += [f"{exp.name}: {e}" for e in check_expected(json.loads(exp.read_text("utf-8")), rows)]
    summary = (f"{r.points} pts, {r.distance_m / 1000:.1f} km, {r.duration_s / 60:.0f} min, "
               f"median {r.median_interval_s:.1f} s")
    return errors, r.warnings, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    a = ap.parse_args(argv)
    paths = a.paths or sorted(Path("traces").glob("*.jsonl"))
    if not paths:
        print("no traces found")
        return 0
    failed = 0
    for p in paths:
        errors, warnings, summary = check_file(p)
        print(f"{'FAIL' if errors else 'ok  '} {p}  ({summary})")
        for e in errors:
            print(f"     error: {e}")
        for w in warnings[:10]:
            print(f"     warning: {w}")
        failed += bool(errors)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
