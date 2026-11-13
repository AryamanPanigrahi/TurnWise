"""Decision points: precomputed fact cards for every fork, flyover entry and junction.

Input is a *route bundle* (see engine/valhalla.py): the route polyline, Valhalla's
manoeuvres, the per-edge attributes along the route, and, for each candidate
fork, the OTHER roads leaving that node. Output is a list of `DecisionPoint`s
sorted by position along the route. This module is pure: no network, so it is
replay-testable (CLAUDE.md: "engine functions are pure and deterministic").

Product rule 1: facts come from the map data only. When the alternatives at a
fork are unknown we still produce a card, but with `alternatives=[]` and a
lower confidence, and never invent a branch.

The card fields follow docs/contracts/fact_card.schema.json. Extra fields
(`maneuver`, `at_m`, `on_route_name`, `alternative_names`) are allowed by the
schema (`additionalProperties: true`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from engine.geometry import LatLon, haversine_m

# Valhalla manoeuvre types (https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/)
TURN_RIGHT = {9, 10, 11}
TURN_LEFT = {14, 15, 16}
U_TURN = {12, 13}
STAY_STRAIGHT, STAY_RIGHT, STAY_LEFT = 22, 23, 24
RAMP_STRAIGHT, RAMP_RIGHT, RAMP_LEFT, EXIT_RIGHT, EXIT_LEFT = 17, 18, 19, 20, 21
ROUNDABOUT_ENTER = 26
FORK_TYPES = {STAY_STRAIGHT, STAY_RIGHT, STAY_LEFT, RAMP_STRAIGHT, RAMP_RIGHT, RAMP_LEFT, EXIT_RIGHT, EXIT_LEFT}

# Manoeuvre type -> contract `maneuver` value (docs/contracts/ask.md)
MANEUVER = {
    **{t: "turn_right" for t in TURN_RIGHT},
    **{t: "turn_left" for t in TURN_LEFT},
    **{t: "u_turn" for t in U_TURN},
    STAY_STRAIGHT: "straight", RAMP_STRAIGHT: "straight",
    STAY_RIGHT: "keep_right", RAMP_RIGHT: "keep_right", EXIT_RIGHT: "keep_right",
    STAY_LEFT: "keep_left", RAMP_LEFT: "keep_left", EXIT_LEFT: "keep_left",
    ROUNDABOUT_ENTER: "roundabout",
}

ELEVATED_WORDS = ("flyover", "overpass", "elevated", "fly over")
UNDERPASS_WORDS = ("underpass", "subway", "under pass")


@dataclass(frozen=True)
class DecisionPoint:
    at_m: float                   # distance from the route start to the decision node
    type: str                     # flyover_vs_service | underpass_vs_surface | fork | junction | roundabout
    on_route: str                 # the branch to take (contract enum)
    alternatives: list[str]       # the other branches
    confidence: float
    maneuver: str | None = None   # turn_left | keep_right | ... (contract maneuver values)
    on_route_name: str | None = None
    alternative_names: list[str] = field(default_factory=list)
    landmark: str | None = None   # filled in later from OSM POIs

    def fact_card(self, distance_m: float) -> dict:
        """The fact card (docs/contracts/fact_card.schema.json) as seen from `distance_m` away."""
        card = {
            "type": self.type,
            "on_route": self.on_route,
            "alternatives": list(self.alternatives),
            "distance_m": max(0.0, round(distance_m)),
            "landmark": self.landmark,
            "confidence": self.confidence,
        }
        if self.maneuver:
            card["maneuver"] = self.maneuver
        if self.on_route_name:
            card["on_route_name"] = self.on_route_name
        if self.alternative_names:
            card["alternative_names"] = list(self.alternative_names)
        return card


# -- edge classification ---------------------------------------------------------
def _names(edge: Mapping) -> str:
    return " ".join(edge.get("names") or []).lower()


def is_elevated(edge: Mapping) -> bool:
    """A flyover: named as one, or flagged as a bridge by OSM."""
    return any(w in _names(edge) for w in ELEVATED_WORDS) or bool(edge.get("bridge"))


def is_underpass(edge: Mapping) -> bool:
    return any(w in _names(edge) for w in UNDERPASS_WORDS) or bool(edge.get("tunnel"))


def is_service(edge: Mapping) -> bool:
    return edge.get("use") == "service_road" or edge.get("road_class") == "service_other"


def branch_label(edge: Mapping) -> str:
    """Contract-style label for a road: flyover | underpass | service_road | surface_road."""
    if is_elevated(edge):
        return "flyover"
    if is_underpass(edge):
        return "underpass"
    if is_service(edge):
        return "service_road"
    return "surface_road"


_ROAD_CODE = re.compile(r"^(NH|SH|AH|MDR|ODR|SR)\s?-?\d+[A-Z]?$", re.IGNORECASE)


def _display_name(edge: Mapping) -> str | None:
    """A name a driver would say: skip highway codes like NH44 / AH43 when a real name exists."""
    names = edge.get("names") or []
    spoken = [n for n in names if not _ROAD_CODE.match(n.strip())]
    return (spoken or names or [None])[0]


# -- building ------------------------------------------------------------------------
def _cumulative_m(route: Sequence[LatLon]) -> list[float]:
    cum = [0.0]
    for a, b in zip(route, route[1:]):
        cum.append(cum[-1] + haversine_m(a, b))
    return cum


def _edge_starting_at(edges: Sequence[Mapping], shape_index: int) -> Mapping | None:
    return next((e for e in edges if e["begin_shape_index"] == shape_index), None)


def _edge_before(edges: Sequence[Mapping], shape_index: int) -> Mapping | None:
    return next((e for e in edges if e["end_shape_index"] == shape_index), None)


def build_decision_points(bundle: Mapping) -> list[DecisionPoint]:
    """Turn a route bundle into decision points, sorted along the route."""
    route = [tuple(p) for p in bundle["route"]]
    cum = _cumulative_m(route)
    edges = bundle["edges"]
    forks = bundle.get("forks", {})            # {"<shape_index>": [outgoing alternative edges]}
    by_index: dict[int, DecisionPoint] = {}

    # 1. Valhalla manoeuvres (turns, keep-left/right, ramps, roundabouts)
    for m in bundle["maneuvers"]:
        kind = m["type"]
        if kind not in MANEUVER:
            continue
        idx = m["begin_shape_index"]
        route_edge = _edge_starting_at(edges, idx)
        alts = forks.get(str(idx)) if kind in FORK_TYPES else None
        by_index[idx] = _make_point(cum[idx], MANEUVER[kind], route_edge, alts, kind in FORK_TYPES)

    # 2. Flyover / underpass entries that Valhalla does not call a manoeuvre,
    #    because the road simply continues (Silk Board: Hosur Road -> flyover).
    for prev, cur in zip(edges, edges[1:]):
        idx = cur["begin_shape_index"]
        if idx in by_index:
            continue
        entering = (is_elevated(cur) and not is_elevated(prev)) or (is_underpass(cur) and not is_underpass(prev))
        if entering and str(idx) in forks:
            by_index[idx] = _make_point(cum[idx], "straight", cur, forks[str(idx)], True)

    return sorted(by_index.values(), key=lambda d: d.at_m)


def _make_point(at_m: float, maneuver: str, route_edge: Mapping | None,
                alts: Sequence[Mapping] | None, is_fork: bool) -> DecisionPoint:
    on_name = _display_name(route_edge) if route_edge else None

    if maneuver == "roundabout":
        return DecisionPoint(at_m, "roundabout", "roundabout", [], 0.9, maneuver, on_name)
    if not is_fork or route_edge is None:
        # A plain turn: the geometry of the turn is the fact; there is no branch to confuse.
        return DecisionPoint(at_m, "junction", maneuver, [], 0.9, maneuver, on_name)

    if not alts:
        # We do not know what the other branch is: say what we DO know, do not guess.
        if is_elevated(route_edge):
            return DecisionPoint(at_m, "flyover_vs_service", "flyover", [], 0.6, maneuver, on_name)
        if is_underpass(route_edge):
            return DecisionPoint(at_m, "underpass_vs_surface", "underpass", [], 0.6, maneuver, on_name)
        side = {"keep_left": "left_fork", "keep_right": "right_fork"}.get(maneuver, "straight")
        return DecisionPoint(at_m, "fork", side, [], 0.5, maneuver, on_name)

    mine = branch_label(route_edge)
    others = sorted({branch_label(a) for a in alts})
    alt_names = [n for n in (_display_name(a) for a in alts) if n]

    if mine == "flyover" and "flyover" not in others:
        return DecisionPoint(at_m, "flyover_vs_service", "flyover", others, 0.9, maneuver, on_name, alt_names)
    if mine in ("service_road", "surface_road") and "flyover" in others:
        on = "service_road" if mine == "service_road" else "surface"
        return DecisionPoint(at_m, "flyover_vs_service", on, ["flyover"], 0.85, maneuver, on_name, alt_names)
    if mine == "underpass" and "underpass" not in others:
        return DecisionPoint(at_m, "underpass_vs_surface", "underpass", ["surface"], 0.9, maneuver, on_name, alt_names)
    if mine != "underpass" and "underpass" in others:
        return DecisionPoint(at_m, "underpass_vs_surface", "surface", ["underpass"], 0.85, maneuver, on_name, alt_names)

    side = {"keep_left": "left_fork", "keep_right": "right_fork"}.get(maneuver, "straight")
    opposite = {"left_fork": "right_fork", "right_fork": "left_fork"}.get(side)
    return DecisionPoint(at_m, "fork", side, [opposite] if opposite else others, 0.8, maneuver, on_name, alt_names)


# -- runtime ---------------------------------------------------------------------------
def upcoming(points: Sequence[DecisionPoint], along_m: float, within_m: float = 1000.0) -> list[dict]:
    """Fact cards for decision points ahead of the vehicle, nearest first."""
    return [p.fact_card(p.at_m - along_m)
            for p in points if 0 <= p.at_m - along_m <= within_m]
