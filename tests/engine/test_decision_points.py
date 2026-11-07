"""Decision points: fact cards from a saved real Valhalla route plus hand-made forks."""

import json
from pathlib import Path

import pytest

from engine.decision_points import build_decision_points, is_elevated, upcoming
from engine.polyline import decode_polyline

BUNDLE = Path(__file__).resolve().parents[1] / "fixtures" / "routes" / "mgroad-ecity.bundle.json"


@pytest.fixture(scope="module")
def real():
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


# -- polyline ------------------------------------------------------------------------
def test_decode_polyline_matches_googles_documented_example():
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


# -- the real MG Road -> Electronic City route ------------------------------------------
def test_real_route_has_the_electronic_city_flyover_card(real):
    cards = [p for p in build_decision_points(real) if p.type == "flyover_vs_service"
             and p.on_route_name == "Electronic City Flyover"]
    assert len(cards) == 1
    card = cards[0]
    assert card.on_route == "flyover"
    assert card.alternatives == ["surface_road"]
    assert card.maneuver == "keep_right"            # Valhalla: "Keep right to take Electronic City Flyover"
    assert card.alternative_names == ["Hosur Road"]  # a spoken name, not the NH44 / AH43 codes
    assert card.confidence >= 0.9
    assert 8000 < card.at_m < 8300


def test_real_route_decision_points_are_sorted_and_inside_the_route(real):
    pts = build_decision_points(real)
    assert [p.at_m for p in pts] == sorted(p.at_m for p in pts)
    assert all(0 <= p.at_m <= real["length_m"] for p in pts)


def test_real_route_underpass_is_recognised(real):
    assert any(p.type == "underpass_vs_surface" and p.on_route == "underpass"
               for p in build_decision_points(real))


def test_unknown_alternatives_are_never_invented(real):
    for p in build_decision_points(real):
        if p.type == "fork":
            assert p.alternatives == [] and p.confidence <= 0.5
        if not p.alternatives and p.type != "junction":
            assert p.confidence < 0.9


def test_upcoming_returns_cards_with_distance_from_the_vehicle(real):
    pts = build_decision_points(real)
    flyover = next(p for p in pts if p.on_route_name == "Electronic City Flyover")
    cards = upcoming(pts, along_m=flyover.at_m - 350, within_m=1000)
    assert cards[0]["type"] == "flyover_vs_service"
    assert cards[0]["distance_m"] == 350
    assert set(["type", "on_route", "alternatives", "distance_m", "landmark", "confidence"]) <= set(cards[0])
    assert upcoming(pts, along_m=flyover.at_m + 10, within_m=5) == []   # already passed


# -- hand-made forks ----------------------------------------------------------------------
ROUTE = [[12.0, 77.0], [12.001, 77.0], [12.002, 77.0], [12.003, 77.0]]


def edge(i, names, use="road", cls="primary", bridge=False, tunnel=False):
    return {"begin_shape_index": i, "end_shape_index": i + 1, "names": names, "use": use,
            "road_class": cls, "bridge": bridge, "tunnel": tunnel, "toll": False,
            "way_id": 100 + i, "lane_count": 2, "length_m": 111.0}


def bundle(maneuver_type, route_edge, alternatives):
    return {"route": ROUTE, "length_m": 333.0,
            "maneuvers": [{"type": maneuver_type, "begin_shape_index": 1}],
            "edges": [edge(0, ["Main Road"]), route_edge, edge(2, ["Main Road"])],
            "forks": {"1": alternatives}}


def alt(names, use="road", cls="primary", bridge=False, tunnel=False):
    return {"names": names, "way_id": 1, "use": use, "road_class": cls, "bridge": bridge, "tunnel": tunnel}


def test_taking_the_service_road_beside_a_flyover():
    b = bundle(24, edge(1, ["Service Road"], use="service_road", cls="service_other"),
               [alt(["Hebbal Flyover"], bridge=True)])
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.alternatives, p.maneuver) == \
        ("flyover_vs_service", "service_road", ["flyover"], "keep_left")


def test_taking_the_flyover_over_a_service_road():
    b = bundle(23, edge(1, ["Ring Road Flyover"], bridge=True),
               [alt(["Service Road"], use="service_road", cls="service_other")])
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.alternatives) == ("flyover_vs_service", "flyover", ["service_road"])


def test_staying_on_the_surface_when_an_underpass_is_the_alternative():
    b = bundle(22, edge(1, ["Cross Road"]), [alt(["Rail Underpass"], tunnel=True)])
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.alternatives) == ("underpass_vs_surface", "surface", ["underpass"])


def test_plain_fork_names_the_opposite_side():
    b = bundle(23, edge(1, ["Right Road"]), [alt(["Left Road"])])
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.alternatives) == ("fork", "right_fork", ["left_fork"])


def test_plain_turn_is_a_junction_without_alternatives():
    b = bundle(15, edge(1, ["Side Street"]), [])
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.maneuver, p.alternatives) == ("junction", "turn_left", "turn_left", [])


def test_start_and_destination_manoeuvres_are_not_decision_points():
    b = bundle(1, edge(1, ["Main Road"]), [])
    b["maneuvers"] = [{"type": 1, "begin_shape_index": 0}, {"type": 4, "begin_shape_index": 3}]
    assert build_decision_points(b) == []


def test_flyover_entry_without_a_valhalla_manoeuvre_is_still_found():
    b = bundle(8, edge(1, ["Silk Board Flyover"], bridge=True), [alt(["Hosur Road"])])
    b["maneuvers"] = []                      # the road just continues: Valhalla says nothing
    (p,) = build_decision_points(b)
    assert (p.type, p.on_route, p.alternatives) == ("flyover_vs_service", "flyover", ["surface_road"])


def test_flyover_entry_with_unknown_alternatives_is_flagged_low_confidence():
    b = bundle(8, edge(1, ["Silk Board Flyover"], bridge=True), [])
    b["maneuvers"] = []
    (p,) = build_decision_points(b)
    assert p.on_route == "flyover" and p.alternatives == [] and p.confidence < 0.7


def test_is_elevated_uses_names_and_bridge_flag():
    assert is_elevated({"names": ["Hebbal Flyover"]})
    assert is_elevated({"names": [], "bridge": True})
    assert not is_elevated({"names": ["Hosur Road"]})
