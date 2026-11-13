"""Wrong-way detection: pure geometry and heading, never the AI model.

CLAUDE.md rule 2: a deviation alert is templated speech driven by this module
alone, with a target of <= 2 s after the deviation is certain.

The detector follows one planned route (a polyline) and is fed GPS fixes one at
a time. It has two independent ways to decide "off route":

* distance: the fix has been farther than a threshold from the route for a
  short, confirmed time. The threshold grows with the fix's reported accuracy,
  so a poor GPS fix does not cause a false alarm.
* heading: the vehicle has pointed more than `heading_off_deg` away from the
  direction of the route for `heading_confirm_s` while moving. This catches
  driving the wrong way along the same road, where distance stays near zero.

It deliberately does NOT know about parallel roads (a flyover and its service
road are ~10 m apart): telling those apart needs the road graph (map-matching
edges), which is a later layer. Here, "on the route" means "within GPS error of
the route line".

Deterministic: the same fixes in the same order always give the same events.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Iterable, Sequence

from engine.geometry import LatLon, Projection, haversine_m, heading_diff_deg, project_to_polyline


@dataclass(frozen=True)
class DetectorConfig:
    off_distance_m: float = 20.0      # minimum distance from route to call a fix "far"
    accuracy_factor: float = 2.5      # far threshold = max(off_distance_m, factor * accuracy)
    confirm_s: float = 1.0            # how long "far" must hold ...
    min_fixes: int = 2                # ... and over how many fixes
    on_distance_m: float = 12.0       # "near" threshold for returning (smaller than far: hysteresis)
    on_accuracy_factor: float = 1.5   # near threshold = max(on_distance_m, factor * accuracy)
    return_confirm_s: float = 3.0     # how long "near and heading right" must hold to return
    heading_off_deg: float = 90.0     # heading this far from the route direction is "wrong way"
    heading_confirm_s: float = 5.0    # ... for this long
    heading_min_speed_mps: float = 2.0  # heading is unreliable when slower than this
    window_back_m: float = 200.0      # while on route, only search this far behind the last progress
    window_ahead_m: float = 1500.0    # ... and this far ahead (stops loops matching the wrong crossing)
    gap_reset_s: float = 10.0         # after a longer gap in fixes, search the whole route again


@dataclass(frozen=True)
class Event:
    event: str                        # "off_route" | "back_on_route"
    ts: str                           # timestamp of the fix that made it certain
    data: dict = field(default_factory=dict)


def parse_ts(raw: str) -> float:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


class WrongWayDetector:
    def __init__(self, route: Sequence[LatLon], config: DetectorConfig | None = None):
        if len(route) < 2:
            raise ValueError("route needs at least 2 vertices")
        self.route = list(route)
        self.cfg = config or DetectorConfig()
        self._cum = [0.0]
        for a, b in zip(self.route, self.route[1:]):
            self._cum.append(self._cum[-1] + haversine_m(a, b))

        self.off_route = False
        self.progress_m: float | None = None   # distance along the route at the last on-route fix
        self._last_along: float | None = None
        self._last_t: float | None = None
        # persistence trackers: (time first seen, number of fixes) or None
        self._far: tuple[float, int] | None = None
        self._wrong_heading: tuple[float, int] | None = None
        self._near: tuple[float, int] | None = None

    # -- projection --------------------------------------------------------
    def _project(self, point: LatLon, windowed: bool) -> Projection:
        if not windowed or self._last_along is None:
            return project_to_polyline(point, self.route)
        n = len(self.route)
        lo = self._last_along - self.cfg.window_back_m
        hi = self._last_along + self.cfg.window_ahead_m
        i0 = min(max(0, bisect.bisect_right(self._cum, lo) - 1), n - 2)
        i1 = max(min(n - 1, bisect.bisect_left(self._cum, hi)), i0 + 1)
        p = project_to_polyline(point, self.route[i0:i1 + 1])
        return replace(p, along_m=p.along_m + self._cum[i0], segment_index=p.segment_index + i0)

    # -- main entry --------------------------------------------------------
    def update(self, fix: dict) -> list[Event]:
        """Feed one GPS fix (a POST /v1/gps point). Returns events it caused (0 or 1)."""
        cfg = self.cfg
        t = parse_ts(fix["ts"])
        if self._last_t is not None and t - self._last_t > cfg.gap_reset_s:
            self._last_along = None
        self._last_t = t

        point = (fix["lat"], fix["lon"])
        acc = fix.get("accuracy") or 0.0
        proj = self._project(point, windowed=not self.off_route)

        heading = fix.get("heading")
        speed = fix.get("speed")
        heading_wrong = (
            heading is not None
            and (speed is None or speed >= cfg.heading_min_speed_mps)
            and heading_diff_deg(heading, proj.bearing_deg) > cfg.heading_off_deg
        )

        if not self.off_route:
            return self._update_on_route(fix, t, proj, acc, heading_wrong)
        return self._update_off_route(fix, t, proj, acc, heading_wrong)

    def _persist(self, tracker: tuple[float, int] | None, active: bool, t: float):
        """Advance a (first_time, count) tracker; None when inactive."""
        if not active:
            return None
        return (t, 1) if tracker is None else (tracker[0], tracker[1] + 1)

    def _update_on_route(self, fix, t, proj, acc, heading_wrong) -> list[Event]:
        cfg = self.cfg
        far_threshold = max(cfg.off_distance_m, cfg.accuracy_factor * acc)
        far = proj.distance_m > far_threshold

        self._far = self._persist(self._far, far, t)
        self._wrong_heading = self._persist(self._wrong_heading, heading_wrong, t)

        reason = None
        if self._far and t - self._far[0] >= cfg.confirm_s and self._far[1] >= cfg.min_fixes:
            reason = "distance"
        elif self._wrong_heading and t - self._wrong_heading[0] >= cfg.heading_confirm_s:
            reason = "heading"

        if reason is None:
            if not far:
                self._last_along = self.progress_m = proj.along_m   # only trust progress near the route
            return []

        self.off_route = True
        self._far = self._wrong_heading = self._near = None
        confidence = (min(1.0, proj.distance_m / (2 * far_threshold)) if reason == "distance" else 0.8)
        return [Event("off_route", fix["ts"], {
            "reason": reason,
            "deviation_m": round(proj.distance_m),
            "confidence": round(confidence, 2),
            # Without the road graph we cannot say "u-turn in 300 m" yet; "reroute" is the
            # honest contract value (docs/contracts/events.md).
            "recovery": {"action": "reroute"},
        })]

    def _update_off_route(self, fix, t, proj, acc, heading_wrong) -> list[Event]:
        cfg = self.cfg
        near_threshold = max(cfg.on_distance_m, cfg.on_accuracy_factor * acc)
        near = proj.distance_m < near_threshold and not heading_wrong

        self._near = self._persist(self._near, near, t)
        if self._near and t - self._near[0] >= cfg.return_confirm_s and self._near[1] >= cfg.min_fixes:
            self.off_route = False
            self._near = None
            self._far = self._wrong_heading = None
            self._last_along = self.progress_m = proj.along_m
            return [Event("back_on_route", fix["ts"], {})]
        return []


def replay(route: Sequence[LatLon], rows: Iterable[dict],
           config: DetectorConfig | None = None) -> list[Event]:
    """Run a whole trace through a fresh detector and return every event."""
    det = WrongWayDetector(route, config)
    events: list[Event] = []
    for row in rows:
        events.extend(det.update(row))
    return events
