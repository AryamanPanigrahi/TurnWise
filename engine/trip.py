"""The runtime engine for one trip: GPS fixes in, events and answers out.

    engine = TripEngine(bundle)              # bundle from engine/valhalla.py
    for fix in gps_fixes:                    # POST /v1/gps points
        for event in engine.update(fix):     # -> WS /v1/trips/{id}/events
            ...
    engine.ask("which_branch", {"options": ["flyover", "service_road"]})
                                             # -> POST /v1/ask response

It joins three pure parts: the wrong-way detector (wrong_way.py), the decision
points (decision_points.py) and route progress. No network, no clock, no randomness.

Rule 1 (CLAUDE.md): every answer comes from the map data and the route. When a
fact is missing, or the vehicle is off the route (so route facts no longer
apply), the answer is `not_sure`; the engine never guesses.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from engine.decision_points import DecisionPoint, build_decision_points
from engine.wrong_way import DetectorConfig, Event, WrongWayDetector

NOT_SURE = {"answer_key": "not_sure", "facts": {}}

BRANCH_TYPES = {"flyover_vs_service", "underpass_vs_surface", "fork"}
BRANCHES = {"flyover", "service_road", "underpass", "surface", "left_fork", "right_fork"}
# docs/contracts/ask.md: maneuver values the voice layer can speak
SPEAKABLE_MANEUVERS = {"turn_left", "turn_right", "keep_left", "keep_right", "u_turn", "roundabout"}
SIDE = {"turn_left": "left", "keep_left": "left", "turn_right": "right", "keep_right": "right",
        "straight": "straight"}

PASSED_TOLERANCE_M = 15.0     # a decision point this far behind us still counts as "next" (GPS jitter)
BRANCH_LOOKAHEAD_M = 3000.0   # which_branch only answers about forks this close
DEFAULT_ANNOUNCE_M = (400.0, 100.0)


def _same_branch(a: str, b: str) -> bool:
    """A driver's "service road" matches our `surface_road`/`service_road` (the road below)."""
    lower = {"service_road", "surface_road", "surface"}
    return a == b or (a in lower and b in lower)


class TripEngine:
    def __init__(self, bundle: Mapping, config: DetectorConfig | None = None,
                 announce_at_m: Sequence[float] = DEFAULT_ANNOUNCE_M, arrive_within_m: float = 30.0):
        self.route = [tuple(p) for p in bundle["route"]]
        self.length_m = float(bundle["length_m"])
        self.points: list[DecisionPoint] = build_decision_points(bundle)
        self.detector = WrongWayDetector(self.route, config)
        self.announce_at_m = sorted(announce_at_m)
        self.arrive_within_m = arrive_within_m
        self.arrived = False
        self.speed_mps: float | None = None          # smoothed speed of recent fixes
        self._announced: set[tuple[int, float]] = set()

    # -- state ------------------------------------------------------------------------
    @property
    def along_m(self) -> float | None:
        return self.detector.progress_m

    @property
    def off_route(self) -> bool:
        return self.detector.off_route

    # -- GPS in -> events out ------------------------------------------------------------
    def update(self, fix: dict) -> list[Event]:
        speed = fix.get("speed")
        if speed is not None and speed >= 0.5:
            self.speed_mps = speed if self.speed_mps is None else 0.8 * self.speed_mps + 0.2 * speed

        events = self.detector.update(fix)
        along = self.along_m
        if along is None or self.off_route:
            return events

        events += self._decision_announcements(fix["ts"], along)

        remaining = self.length_m - along
        if not self.arrived and remaining <= self.arrive_within_m:
            self.arrived = True
            events.append(Event("arrived", fix["ts"], {"distance_m": max(0, round(remaining))}))
        return events

    def _decision_announcements(self, ts: str, along: float) -> list[Event]:
        out = []
        for i, p in enumerate(self.points):
            dist = p.at_m - along
            if dist < 0:
                continue
            inside = [t for t in self.announce_at_m if dist <= t]
            pending = [t for t in inside if (i, t) not in self._announced]
            if not pending:
                continue
            # first fix already inside the closer ring: announce once, at the closest ring
            self._announced.update((i, t) for t in inside)
            out.append(Event("decision_point_ahead", ts, p.fact_card(dist)))
        return out

    # -- questions in -> facts out ---------------------------------------------------------
    def ask(self, intent: str, slots: Mapping | None = None) -> dict:
        """Answer a driver question as {answer_key, facts} (docs/contracts/ask.md)."""
        slots = slots or {}
        along = self.along_m
        if along is None:
            return dict(NOT_SURE)                        # no position on the route yet

        if intent == "am_i_wrong":
            if self.off_route:
                return {"answer_key": "am_i_wrong.off_route", "facts": {"recovery_action": "reroute"}}
            return {"answer_key": "am_i_wrong.on_route", "facts": {}}

        if self.off_route:
            return dict(NOT_SURE)                        # route facts do not apply off the route

        if intent == "which_branch":
            return self._which_branch(along, slots.get("options") or [])
        if intent == "left_or_right":
            return self._left_or_right(along)
        if intent == "distance_to_next":
            return self._distance_to_next(along)
        if intent == "eta":
            return self._eta(along)
        return dict(NOT_SURE)                            # repeat/unknown are the voice layer's job

    def _ahead(self, along: float) -> list[DecisionPoint]:
        return [p for p in self.points if p.at_m - along >= -PASSED_TOLERANCE_M]

    def _which_branch(self, along: float, options: Sequence[str]) -> dict:
        for p in self._ahead(along):
            if p.type not in BRANCH_TYPES:
                continue
            dist = p.at_m - along
            if dist > BRANCH_LOOKAHEAD_M:
                break
            if p.on_route not in BRANCHES:
                return dict(NOT_SURE)
            mentioned = [p.on_route, *p.alternatives]
            if options and not any(_same_branch(o, m) for o in options for m in mentioned):
                continue                                 # a different fork than the one asked about
            return {"answer_key": f"which_branch.{p.on_route}",
                    "facts": {"on_route": p.on_route, "distance_m": max(0, round(dist)),
                              "landmark": p.landmark, "confidence": p.confidence}}
        return dict(NOT_SURE)

    def _left_or_right(self, along: float) -> dict:
        nxt = next(iter(self._ahead(along)), None)
        side = SIDE.get(nxt.maneuver) if nxt else None
        if nxt is None or side is None:
            return dict(NOT_SURE)
        return {"answer_key": f"left_or_right.{side}",
                "facts": {"distance_m": max(0, round(nxt.at_m - along)), "landmark": nxt.landmark,
                          "confidence": nxt.confidence}}

    def _distance_to_next(self, along: float) -> dict:
        nxt = next((p for p in self._ahead(along) if p.maneuver in SPEAKABLE_MANEUVERS), None)
        if nxt is not None:
            return {"answer_key": "distance_to_next",
                    "facts": {"distance_m": max(0, round(nxt.at_m - along)), "maneuver": nxt.maneuver}}
        return {"answer_key": "distance_to_next",
                "facts": {"distance_m": max(0, round(self.length_m - along)), "maneuver": "arrive"}}

    def _eta(self, along: float) -> dict:
        if not self.speed_mps:
            return dict(NOT_SURE)                        # no recent speed: any ETA would be a guess
        remaining = max(0.0, self.length_m - along)
        return {"answer_key": "eta",
                "facts": {"remaining_m": round(remaining), "eta_s": round(remaining / max(self.speed_mps, 3.0))}}
