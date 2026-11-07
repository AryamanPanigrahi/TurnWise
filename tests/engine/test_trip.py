"""The whole engine on the real MG Road -> Electronic City route, driven by synthetic GPS."""

import json
from pathlib import Path

import pytest

from engine.geometry import bearing_deg, destination, haversine_m
from engine.synthetic import drive
from engine.trip import TripEngine
from voice.answer import render_answer

BUNDLE = Path(__file__).resolve().parents[1] / "fixtures" / "routes" / "mgroad-ecity.bundle.json"
SPEED = 15.0


@pytest.fixture(scope="module")
def bundle():
    return json.loads(BUNDLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def full_drive(bundle):
    route = [tuple(p) for p in bundle["route"]]
    return drive(route, trip_id="t", speed_mps=SPEED, noise_m=4.0, seed=11)


def run(bundle, rows):
    eng = TripEngine(bundle)
    events = []
    for r in rows:
        events += eng.update(r)
    return eng, events


def at(bundle, along_m, speed=SPEED):
    """Engine fed the real route up to `along_m` metres, as if the car is there now."""
    route = [tuple(p) for p in bundle["route"]]
    d = drive(route, trip_id="t", speed_mps=speed, noise_m=3.0, seed=5)
    eng = TripEngine(bundle)
    for r, _ in zip(d.rows, range(int(along_m / speed) + 1)):
        eng.update(r)
    return eng


# -- events over a whole clean drive --------------------------------------------------------
def test_clean_drive_has_no_off_route_and_arrives_once(bundle, full_drive):
    _, events = run(bundle, full_drive.rows)
    kinds = [e.event for e in events]
    assert "off_route" not in kinds
    assert kinds.count("arrived") == 1
    assert kinds[-1] == "arrived"


def test_each_decision_point_is_announced_at_400_and_100_m(bundle, full_drive):
    eng, events = run(bundle, full_drive.rows)
    flyover = next(p for p in eng.points if p.on_route_name == "Electronic City Flyover")
    cards = [e.data for e in events if e.event == "decision_point_ahead"
             and e.data.get("on_route_name") == "Electronic City Flyover"]
    assert len(cards) == 2
    assert cards[0]["distance_m"] == pytest.approx(400, abs=2 * SPEED)
    assert cards[1]["distance_m"] == pytest.approx(100, abs=2 * SPEED)
    assert cards[0]["type"] == "flyover_vs_service" and cards[0]["on_route"] == "flyover"
    assert flyover.at_m > 8000


def test_announcements_never_repeat(bundle, full_drive):
    eng, events = run(bundle, full_drive.rows)
    ahead = [e.data for e in events if e.event == "decision_point_ahead"]
    assert 0 < len(ahead) <= 2 * len(eng.points)           # at most one per ring per decision point
    # a uniquely named place is announced twice, each time closer than the last
    for name in ("Electronic City Flyover", "Silk Board Flyover", "Madiwala Underpass"):
        dists = [c["distance_m"] for c in ahead if c.get("on_route_name") == name]
        assert len(dists) == 2 and dists[0] > dists[1], name


# -- answers ------------------------------------------------------------------------------------
def test_which_branch_before_the_flyover(bundle):
    flyover_at = next(p.at_m for p in TripEngine(bundle).points if p.on_route_name == "Electronic City Flyover")
    eng = at(bundle, flyover_at - 350)
    ans = eng.ask("which_branch", {"options": ["flyover", "service_road"]})
    assert ans["answer_key"] == "which_branch.flyover"
    assert ans["facts"]["distance_m"] == pytest.approx(350, abs=3 * SPEED)
    assert ans["facts"]["confidence"] >= 0.9
    # and Ram's renderer turns it into a sentence
    text = render_answer("en", ans["answer_key"], ans["facts"]).text
    assert "flyover" in text and "metres" in text


def test_which_branch_ignores_forks_the_driver_did_not_ask_about(bundle):
    eng = at(bundle, 5000)           # the next branch is the Madiwala underpass
    assert eng.ask("which_branch", {"options": ["underpass"]})["answer_key"] == "which_branch.underpass"
    # asking about a flyover/service road here: the next relevant fork is not within lookahead
    assert eng.ask("which_branch", {"options": ["left_fork", "right_fork"]})["answer_key"] == "not_sure"


def test_left_or_right_and_distance_at_the_start(bundle):
    eng = at(bundle, 60)
    lr = eng.ask("left_or_right")
    assert lr["answer_key"] == "left_or_right.right"      # Turn right onto Brigade Road
    assert lr["facts"]["distance_m"] == pytest.approx(160, abs=3 * SPEED)
    d = eng.ask("distance_to_next")
    assert d["facts"]["maneuver"] == "turn_right"


def test_distance_to_next_at_the_end_is_the_arrival(bundle):
    eng = at(bundle, bundle["length_m"] - 1500)
    last_turn = [p for p in eng.points if p.at_m > bundle["length_m"] - 1500]
    ans = eng.ask("distance_to_next")
    assert ans["answer_key"] == "distance_to_next"
    assert last_turn or ans["facts"]["maneuver"] == "arrive"


def test_eta_uses_recent_speed(bundle):
    eng = at(bundle, 2000)
    ans = eng.ask("eta")
    remaining = bundle["length_m"] - 2000
    assert ans["facts"]["remaining_m"] == pytest.approx(remaining, abs=100)
    assert ans["facts"]["eta_s"] == pytest.approx(remaining / SPEED, rel=0.15)


def test_am_i_wrong_on_route(bundle):
    assert at(bundle, 1000).ask("am_i_wrong")["answer_key"] == "am_i_wrong.on_route"


def test_nothing_is_known_before_the_first_fix(bundle):
    eng = TripEngine(bundle)
    for intent in ("which_branch", "left_or_right", "distance_to_next", "eta", "am_i_wrong", "repeat"):
        assert eng.ask(intent)["answer_key"] == "not_sure"


def test_unknown_and_repeat_intents_are_not_answered_by_the_engine(bundle):
    eng = at(bundle, 1000)
    assert eng.ask("repeat")["answer_key"] == "not_sure"
    assert eng.ask("unknown")["answer_key"] == "not_sure"


# -- going wrong ---------------------------------------------------------------------------------
def test_wrong_turn_raises_off_route_and_stops_route_answers(bundle):
    route = [tuple(p) for p in bundle["route"]]
    # follow the route for ~2 km, then drive straight on in the direction of the last segment, off the route
    i = next(k for k in range(1, len(route)) if sum(haversine_m(route[j], route[j + 1]) for j in range(k)) > 2000)
    heading = (bearing_deg(route[i - 1], route[i]) + 90) % 360       # turn 90 degrees away
    path = route[:i] + [destination(route[i - 1], heading, 600)]
    d = drive(path, trip_id="t", speed_mps=SPEED, noise_m=4.0, seed=3)

    eng, events = run(bundle, d.rows)
    assert [e.event for e in events if e.event in ("off_route", "back_on_route")] == ["off_route"]
    assert eng.off_route

    assert eng.ask("am_i_wrong")["answer_key"] == "am_i_wrong.off_route"
    for intent in ("which_branch", "left_or_right", "distance_to_next", "eta"):
        assert eng.ask(intent)["answer_key"] == "not_sure"      # route facts no longer apply


def test_no_announcements_while_off_route(bundle):
    route = [tuple(p) for p in bundle["route"]]
    i = next(k for k in range(1, len(route)) if sum(haversine_m(route[j], route[j + 1]) for j in range(k)) > 2000)
    heading = (bearing_deg(route[i - 1], route[i]) + 90) % 360
    d = drive(route[:i] + [destination(route[i - 1], heading, 600)], trip_id="t", speed_mps=SPEED, seed=3)
    eng, events = run(bundle, d.rows)
    off_at = next(k for k, e in enumerate(events) if e.event == "off_route")
    assert not any(e.event in ("decision_point_ahead", "arrived") for e in events[off_at:])
