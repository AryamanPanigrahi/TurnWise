"""A scripted stand-in for POST /v1/ask, for laptop demos before the backend exists.

It walks a pretend trip: each question moves the vehicle forward a bit, so
repeated questions get shrinking distances. Facts follow docs/contracts/ask.md.
This is test scaffolding only — it is NOT the route engine.
"""

from __future__ import annotations

from typing import Any, Mapping

# One pretend route (Bengaluru-flavoured), distances measured from the trip start.
SCENARIO = [
    {"at_m": 600, "type": "flyover_vs_service", "on_route": "flyover",
     "landmark": "Indian Oil petrol bunk"},
    {"at_m": 1400, "type": "junction", "maneuver": "turn_left", "landmark": "Ganesha temple"},
    {"at_m": 2600, "type": "junction", "maneuver": "turn_right", "landmark": None},
]
TRIP_LENGTH_M = 5200
SPEED_MPS = 8.0


class FakeEngine:
    def __init__(self, step_m: float = 120.0, off_route: bool = False):
        self.position_m = 0.0
        self.step_m = step_m
        self.off_route = off_route

    def _next(self) -> dict | None:
        return next((d for d in SCENARIO if d["at_m"] > self.position_m), None)

    def __call__(self, trip_id: str, intent: str, slots: Mapping[str, Any]) -> dict:
        self.position_m = min(self.position_m + self.step_m, TRIP_LENGTH_M)
        nxt = self._next()
        dist = (nxt["at_m"] - self.position_m) if nxt else None

        if intent == "am_i_wrong":
            if self.off_route:
                return {"answer_key": "am_i_wrong.off_route",
                        "facts": {"recovery_action": "u_turn", "distance_m": 300}}
            return {"answer_key": "am_i_wrong.on_route", "facts": {}}

        if intent == "eta":
            remaining = TRIP_LENGTH_M - self.position_m
            return {"answer_key": "eta", "facts": {"remaining_m": remaining, "eta_s": remaining / SPEED_MPS}}

        if nxt is None:
            return {"answer_key": "not_sure", "facts": {}}

        if intent == "which_branch":
            if "on_route" not in nxt:  # next decision isn't a branch: don't guess
                return {"answer_key": "not_sure", "facts": {}}
            return {"answer_key": f"which_branch.{nxt['on_route']}",
                    "facts": {"on_route": nxt["on_route"], "distance_m": dist,
                              "landmark": nxt["landmark"], "confidence": 0.9}}

        if intent == "left_or_right":
            m = nxt.get("maneuver")
            side = {"turn_left": "left", "turn_right": "right"}.get(m, "straight")
            return {"answer_key": f"left_or_right.{side}",
                    "facts": {"distance_m": dist, "landmark": nxt.get("landmark")}}

        if intent == "distance_to_next":
            m = nxt.get("maneuver") or ("keep_left" if nxt["on_route"] == "service_road" else "keep_right")
            return {"answer_key": "distance_to_next", "facts": {"distance_m": dist, "maneuver": m}}

        return {"answer_key": "not_sure", "facts": {}}
