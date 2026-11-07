"""Synthetic GPS drives, for testing the engine before real drives are recorded.

Pure and deterministic: the same `seed` always gives the same noisy trace, so a
test failure can be reproduced exactly. Output rows have exactly the fields of
a `POST /v1/gps` point (docs/contracts/gps.md), the same shape as the files in
`traces/`, so the replay tests treat synthetic and real drives alike.

Typical use::

    route = path_from_legs((12.9756, 77.6066), [(90, 2000)])        # 2 km east
    taken = path_from_legs((12.9756, 77.6066), [(90, 1000), (180, 1000)])  # turns south
    d = drive(taken, trip_id="t1", seed=1)
    expected = expected_events(d, route)   # off_route ~4 s after the turn
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from engine.geometry import LatLon, bearing_deg, destination, haversine_m, project_to_polyline

DEFAULT_START = datetime(2026, 11, 7, 4, 30, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Drive:
    rows: list[dict]      # noisy fixes in the POST /v1/gps point shape
    truth: list[LatLon]   # the true, noise-free position for each row


def path_from_legs(start: LatLon, legs: Sequence[tuple[float, float]]) -> list[LatLon]:
    """Build a polyline from a start point and (bearing_deg, length_m) legs."""
    path = [start]
    for bearing, length in legs:
        path.append(destination(path[-1], bearing, length))
    return path


def _cumulative(path: Sequence[LatLon]) -> list[float]:
    cum = [0.0]
    for a, b in zip(path, path[1:]):
        cum.append(cum[-1] + haversine_m(a, b))
    return cum


def _point_at(path: Sequence[LatLon], cum: Sequence[float], s: float) -> tuple[LatLon, float]:
    """Position and direction of travel after s metres along the path."""
    s = max(0.0, min(s, cum[-1]))
    for i in range(len(path) - 1):
        if s <= cum[i + 1] or i == len(path) - 2:
            brg = bearing_deg(path[i], path[i + 1])
            return destination(path[i], brg, s - cum[i]), brg
    raise AssertionError("unreachable")


def _format_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def drive(
    path: Sequence[LatLon],
    *,
    trip_id: str,
    start_ts: datetime = DEFAULT_START,
    speed_mps: float = 10.0,
    hz: float = 1.0,
    noise_m: float = 4.0,
    heading_noise_deg: float = 2.0,
    seed: int = 0,
) -> Drive:
    """Drive along `path` at constant speed, emitting one noisy fix per 1/hz seconds.

    `noise_m` is the standard deviation of the position error in each of north
    and east. Set it to 0 for a perfect trace.
    """
    if len(path) < 2:
        raise ValueError("path needs at least 2 vertices")
    if speed_mps <= 0 or hz <= 0:
        raise ValueError("speed_mps and hz must be positive")

    rng = random.Random(seed)
    cum = _cumulative(path)
    dt = 1.0 / hz
    n = int(cum[-1] / (speed_mps * dt) + 1e-3) + 1  # tolerance: 1999.9999 m must count as 2000 m
    accuracy = round(max(3.0, 1.5 * noise_m), 1)

    rows: list[dict] = []
    truth: list[LatLon] = []
    for i in range(n):
        pos, brg = _point_at(path, cum, i * speed_mps * dt)
        truth.append(pos)
        noisy = pos
        if noise_m > 0:
            noisy = destination(noisy, 0.0, rng.gauss(0.0, noise_m))
            noisy = destination(noisy, 90.0, rng.gauss(0.0, noise_m))
        rows.append({
            "trip_id": trip_id,
            "ts": _format_ts(start_ts + timedelta(seconds=i * dt)),
            "lat": round(noisy[0], 6),
            "lon": round(noisy[1], 6),
            "speed": round(max(0.0, speed_mps + rng.gauss(0.0, 0.3)), 2),
            "heading": round(brg + rng.gauss(0.0, heading_noise_deg), 1) % 360.0,  # round first: 359.96 -> 360.0 is out of range
            "accuracy": accuracy,
        })
    return Drive(rows=rows, truth=truth)


def first_time_off_route(d: Drive, route: Sequence[LatLon], threshold_m: float = 40.0) -> str | None:
    """Timestamp of the first fix whose TRUE position is > threshold_m from the route.

    This is the ground truth for "the wrong turn became certain": the driver is
    clearly on a different road. It uses the noise-free positions, so it does
    not depend on how well the engine copes with noise.
    """
    for row, pos in zip(d.rows, d.truth):
        if project_to_polyline(pos, route).distance_m > threshold_m:
            return row["ts"]
    return None


def expected_events(d: Drive, route: Sequence[LatLon], *, name: str, notes: str = "",
                    threshold_m: float = 40.0) -> dict:
    """Build the `<name>.expected.json` content (traces/README.md format)."""
    events = []
    ts = first_time_off_route(d, route, threshold_m)
    if ts is not None:
        events.append({"event": "off_route", "ts": ts,
                       "note": f"true position > {threshold_m:.0f} m from the planned route"})
    return {"trace": f"{name}.jsonl", "clean": ts is None, "notes": notes, "events": events}


def write_trace(directory: Path, name: str, d: Drive, expected: dict) -> None:
    """Write `<name>.jsonl` and `<name>.expected.json` into `directory`."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in d.rows), encoding="utf-8")
    (directory / f"{name}.expected.json").write_text(
        json.dumps(expected, indent=2) + "\n", encoding="utf-8")
