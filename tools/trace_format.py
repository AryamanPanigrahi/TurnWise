"""Recorded GPS traces: read GPX/CSV logger files, write and check `.jsonl` traces.

A trace is one JSON object per line, with exactly the fields of a
`POST /v1/gps` point (docs/contracts/gps.md), so replay tests feed the engine
the same shape the app will send:

    {"trip_id": "...", "ts": "2026-11-05T04:31:07.000Z", "lat": 12.97, "lon": 77.59,
     "speed": 8.3, "heading": 274.0, "accuracy": 6.5}

Pure functions, standard library only, no network.
"""

from __future__ import annotations

import csv
import io
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Iterable

EARTH_R_M = 6_371_008.8
STATIONARY_MPS = 0.5      # below this, heading is unreliable -> null (contract)
MAX_GAP_S = 5.0           # longer gaps are reported by `check`
MAX_PLAUSIBLE_MPS = 50.0  # 180 km/h; faster jumps are GPS glitches


@dataclass(frozen=True)
class Point:
    trip_id: str
    ts: str
    lat: float
    lon: float
    speed: float | None = None
    heading: float | None = None
    accuracy: float | None = None


# -- geometry ------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


# -- time ----------------------------------------------------------------------
def parse_ts(raw: str) -> datetime:
    """Parse an ISO-8601 time. A time without an offset is assumed to be UTC."""
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _seconds(ts: str) -> float:
    return parse_ts(ts).timestamp()


# -- readers -------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _num(raw: str | None) -> float | None:
    if raw is None or raw.strip() == "":
        return None
    v = float(raw)
    return None if math.isnan(v) else v


def read_gpx(text: str, trip_id: str) -> list[Point]:
    """Read track points from GPX 1.0 or 1.1.

    `speed`, `course` and `accuracy` are picked up wherever the logger put them
    (GPX 1.0 children or 1.1 `<extensions>`, any namespace). `hdop` is *not*
    turned into metres: that conversion depends on the phone, so accuracy stays
    null rather than guessed.
    """
    root = ET.fromstring(text)
    out: list[Point] = []
    for el in root.iter():
        if _local(el.tag) != "trkpt":
            continue
        vals: dict[str, str] = {}
        for child in el.iter():
            name = _local(child.tag)
            if child is not el and child.text and name not in vals:
                vals[name] = child.text
        if "time" not in vals:
            continue
        out.append(Point(
            trip_id=trip_id,
            ts=format_ts(parse_ts(vals["time"])),
            lat=float(el.attrib["lat"]),
            lon=float(el.attrib["lon"]),
            speed=_num(vals.get("speed")),
            heading=_num(vals.get("course") or vals.get("bearing") or vals.get("heading")),
            accuracy=_num(vals.get("accuracy")),
        ))
    return out


_CSV_COLS = {
    "ts": ("time", "timestamp", "date time", "datetime", "ts"),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "long", "longitude"),
    "speed": ("speed", "speed(m/s)", "speed_mps"),
    "heading": ("bearing", "course", "heading"),
    "accuracy": ("accuracy", "accuracy(m)", "horizontal_accuracy"),
}


def read_csv(text: str, trip_id: str) -> list[Point]:
    """Read a CSV with a header row (GPSLogger's CSV export works as is).

    Speed must already be in m/s. Times without an offset are taken as UTC.
    """
    rows = csv.DictReader(io.StringIO(text))
    header = {h.strip().lower(): h for h in (rows.fieldnames or [])}
    col: dict[str, str] = {}
    for key, names in _CSV_COLS.items():
        for n in names:
            if n in header:
                col[key] = header[n]
                break
    missing = {"ts", "lat", "lon"} - col.keys()
    if missing:
        raise ValueError(f"CSV is missing column(s): {', '.join(sorted(missing))}")
    out = []
    for r in rows:
        if not (r.get(col["lat"]) or "").strip():
            continue
        out.append(Point(
            trip_id=trip_id,
            ts=format_ts(parse_ts(r[col["ts"]])),
            lat=float(r[col["lat"]]),
            lon=float(r[col["lon"]]),
            speed=_num(r.get(col["speed"])) if "speed" in col else None,
            heading=_num(r.get(col["heading"])) if "heading" in col else None,
            accuracy=_num(r.get(col["accuracy"])) if "accuracy" in col else None,
        ))
    return out


# -- cleaning ------------------------------------------------------------------
def sort_dedupe(points: Iterable[Point]) -> list[Point]:
    """Sort by time and keep the first point for each timestamp (like the server)."""
    seen: set[str] = set()
    out = []
    for p in sorted(points, key=lambda p: _seconds(p.ts)):
        if p.ts not in seen:
            seen.add(p.ts)
            out.append(p)
    return out


def fill_motion(points: list[Point]) -> list[Point]:
    """Derive missing speed/heading from the previous point.

    Heading is set to null when the vehicle is (nearly) stationary, as the
    contract requires, even if the logger reported one.
    """
    out: list[Point] = []
    for i, p in enumerate(points):
        speed, heading = p.speed, p.heading
        if i > 0 and (speed is None or heading is None):
            q = points[i - 1]
            dt = _seconds(p.ts) - _seconds(q.ts)
            d = haversine_m(q.lat, q.lon, p.lat, p.lon)
            if speed is None and dt > 0:
                speed = round(d / dt, 2)
            if heading is None and d > 0:
                heading = round(bearing_deg(q.lat, q.lon, p.lat, p.lon), 1)
        if speed is not None and speed < STATIONARY_MPS:
            heading = None
        out.append(replace(p, speed=speed, heading=heading))
    return out


def trim_ends(points: list[Point], start_m: float, end_m: float) -> list[Point]:
    """Drop points within `start_m` of the first point and `end_m` of the last.

    Privacy (DPDP): drives often start and end at someone's home. Trimming the
    ends keeps that location out of the repo.
    """
    if not points:
        return points
    first, last = 0, len(points) - 1
    if start_m > 0:
        a = points[0]
        first = next((i for i, p in enumerate(points)
                      if haversine_m(a.lat, a.lon, p.lat, p.lon) > start_m), len(points))
    if end_m > 0:
        b = points[-1]
        last = next((i for i in range(len(points) - 1, -1, -1)
                     if haversine_m(b.lat, b.lon, points[i].lat, points[i].lon) > end_m), -1)
    return points[first:last + 1]


def convert(text: str, fmt: str, trip_id: str, trim_start_m: float = 0.0,
            trim_end_m: float = 0.0) -> list[Point]:
    reader = {"gpx": read_gpx, "csv": read_csv}[fmt]
    pts = sort_dedupe(reader(text, trip_id))
    pts = trim_ends(pts, trim_start_m, trim_end_m)
    return fill_motion(pts)


# -- jsonl ---------------------------------------------------------------------
def dumps_jsonl(points: Iterable[Point]) -> str:
    return "".join(json.dumps(asdict(p), ensure_ascii=False) + "\n" for p in points)


def loads_jsonl(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# -- checking ------------------------------------------------------------------
@dataclass
class Report:
    points: int = 0
    duration_s: float = 0.0
    distance_m: float = 0.0
    median_interval_s: float = 0.0
    errors: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        self.errors = self.errors or []
        self.warnings = self.warnings or []


_FIELDS = ("trip_id", "ts", "lat", "lon", "speed", "heading", "accuracy")


def check_points(rows: list[dict]) -> Report:
    """Check a trace against the gps contract and flag recording problems."""
    r = Report(points=len(rows))
    if not rows:
        r.errors.append("trace is empty")
        return r
    times: list[float] = []
    for i, row in enumerate(rows, 1):
        missing = [f for f in _FIELDS if f not in row]
        if missing:
            r.errors.append(f"line {i}: missing {', '.join(missing)}")
            continue
        try:
            if not str(row["ts"]).endswith("Z"):
                raise ValueError
            times.append(parse_ts(row["ts"]).timestamp())
        except (ValueError, TypeError):
            r.errors.append(f"line {i}: ts must be UTC ISO-8601 ending in Z")
            continue
        if not (-90 <= row["lat"] <= 90 and -180 <= row["lon"] <= 180):
            r.errors.append(f"line {i}: lat/lon out of range")
        if row["speed"] is not None and row["speed"] < 0:
            r.errors.append(f"line {i}: negative speed")
        if row["heading"] is not None and not 0 <= row["heading"] < 360:
            r.errors.append(f"line {i}: heading must be in [0, 360)")
        if row["accuracy"] is not None and row["accuracy"] < 0:
            r.errors.append(f"line {i}: negative accuracy")
    if len({row.get("trip_id") for row in rows}) > 1:
        r.errors.append("more than one trip_id in the trace")
    if r.errors:
        return r

    intervals = []
    for i in range(1, len(rows)):
        dt = times[i] - times[i - 1]
        if dt <= 0:
            r.errors.append(f"line {i + 1}: ts not strictly increasing")
            continue
        intervals.append(dt)
        d = haversine_m(rows[i - 1]["lat"], rows[i - 1]["lon"], rows[i]["lat"], rows[i]["lon"])
        r.distance_m += d
        if dt > MAX_GAP_S:
            r.warnings.append(f"line {i + 1}: {dt:.0f} s gap in fixes")
        if d / dt > MAX_PLAUSIBLE_MPS:
            r.warnings.append(f"line {i + 1}: jump of {d:.0f} m in {dt:.0f} s (GPS glitch?)")
    r.duration_s = times[-1] - times[0]
    if intervals:
        s = sorted(intervals)
        r.median_interval_s = s[len(s) // 2]
        if r.median_interval_s > 1.5:
            r.warnings.append(f"median interval {r.median_interval_s:.1f} s; record at 1 Hz")
    return r


EXPECTED_EVENTS = {"off_route", "back_on_route", "decision_point_ahead", "arrived"}


def check_expected(expected: dict, rows: list[dict]) -> list[str]:
    """Check a `<trace>.expected.json` file against its trace. Returns errors."""
    errs: list[str] = []
    if not isinstance(expected.get("clean"), bool):
        errs.append("'clean' must be true or false")
    events = expected.get("events")
    if not isinstance(events, list):
        return errs + ["'events' must be a list"]
    if not rows:
        return errs
    t0, t1 = parse_ts(rows[0]["ts"]).timestamp(), parse_ts(rows[-1]["ts"]).timestamp()
    for i, ev in enumerate(events, 1):
        if ev.get("event") not in EXPECTED_EVENTS:
            errs.append(f"event {i}: unknown event {ev.get('event')!r}")
        try:
            t = parse_ts(ev["ts"]).timestamp()
        except (KeyError, ValueError, TypeError):
            errs.append(f"event {i}: needs a ts")
            continue
        if not t0 <= t <= t1:
            errs.append(f"event {i}: ts is outside the trace")
    if expected.get("clean") and any(e.get("event") == "off_route" for e in events):
        errs.append("a clean drive cannot expect off_route events")
    return errs


def expected_stub(trace_file: str, clean: bool) -> dict:
    return {
        "trace": trace_file,
        "clean": clean,
        "notes": "",
        "events": [],
    }
