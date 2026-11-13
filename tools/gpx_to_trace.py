"""Convert a GPS logger export (GPX or CSV) into a trace in `traces/`.

    python -m tools.gpx_to_trace drive.gpx traces/2026-11-07_mg-road_ecity_01.jsonl \
        --trim-start-m 200 --trim-end-m 200

Also writes `<name>.expected.json` next to the trace if it doesn't exist yet,
for you to fill in with the wrong turns you made. See traces/README.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.trace_format import check_points, convert, dumps_jsonl, expected_stub, loads_jsonl


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path, help="GPX or CSV file from the GPS logger app")
    ap.add_argument("dst", type=Path, help="output .jsonl, normally under traces/")
    ap.add_argument("--trip-id", help="defaults to the output file name")
    ap.add_argument("--trim-start-m", type=float, default=200.0,
                    help="drop points this close to the start (privacy; default 200)")
    ap.add_argument("--trim-end-m", type=float, default=200.0,
                    help="drop points this close to the end (privacy; default 200)")
    ap.add_argument("--clean", action="store_true",
                    help="mark the drive as having no wrong turns in the expected file")
    a = ap.parse_args(argv)

    fmt = a.src.suffix.lower().lstrip(".")
    if fmt not in ("gpx", "csv"):
        print(f"error: {a.src} is not .gpx or .csv", file=sys.stderr)
        return 2
    if a.dst.suffix != ".jsonl":
        print("error: output must end in .jsonl", file=sys.stderr)
        return 2
    trip_id = a.trip_id or f"trace_{a.dst.stem}"
    points = convert(a.src.read_text(encoding="utf-8"), fmt, trip_id,
                     a.trim_start_m, a.trim_end_m)
    text = dumps_jsonl(points)
    report = check_points(loads_jsonl(text))
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    if report.errors:
        return 1
    a.dst.parent.mkdir(parents=True, exist_ok=True)
    a.dst.write_text(text, encoding="utf-8")
    exp = a.dst.with_suffix(".expected.json")
    if not exp.exists():
        exp.write_text(json.dumps(expected_stub(a.dst.name, a.clean), indent=2) + "\n",
                       encoding="utf-8")
    for w in report.warnings[:20]:
        print(f"warning: {w}")
    print(f"wrote {a.dst}: {report.points} points, {report.distance_m / 1000:.1f} km, "
          f"{report.duration_s / 60:.0f} min")
    print(f"next: fill in {exp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
