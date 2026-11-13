"""Wrong-way detector, tested on synthetic drives with known ground truth.

The pass rule is CLAUDE.md's: every wrong turn flagged within 2 s of the moment
it became certain (engine.synthetic.first_time_off_route), never before the car
actually left the route, and zero alerts on clean drives.
"""

import pytest

from engine.geometry import project_to_polyline
from engine.synthetic import drive, first_time_off_route, path_from_legs
from engine.wrong_way import DetectorConfig, WrongWayDetector, replay
from tools.trace_format import parse_ts

START = (12.9756, 77.6066)
ROUTE = path_from_legs(START, [(90, 2000)])                   # 2 km due east
T_JUNCTION = 100.0                                            # 1000 m at 10 m/s
SEEDS = range(40)


def t_of(row_or_ts) -> float:
    ts = row_or_ts["ts"] if isinstance(row_or_ts, dict) else row_or_ts
    return parse_ts(ts).timestamp()


def first_left_route(d, route, eps_m=1.0) -> str:
    """Timestamp of the first fix whose true position is more than eps_m off the route."""
    for row, pos in zip(d.rows, d.truth):
        if project_to_polyline(pos, route).distance_m > eps_m:
            return row["ts"]
    raise AssertionError("drive never left the route")


def offs(events):
    return [e for e in events if e.event == "off_route"]


# -- no false alarms -----------------------------------------------------------
@pytest.mark.parametrize("noise_m", [4.0, 8.0])
def test_clean_noisy_drives_raise_nothing(noise_m):
    for seed in SEEDS:
        d = drive(ROUTE, trip_id="t", noise_m=noise_m, seed=seed)
        assert replay(ROUTE, d.rows) == [], f"false alarm with seed {seed}"


def test_clean_drive_along_a_curvy_route():
    # S-bends with 60-degree turns: heading changes a lot but the car stays on the route.
    route = path_from_legs(START, [(90, 400), (30, 400), (90, 400), (150, 400), (90, 400)])
    for seed in SEEDS:
        d = drive(route, trip_id="t", noise_m=4.0, seed=seed)
        assert replay(route, d.rows) == [], f"false alarm with seed {seed}"


def test_single_gps_glitch_does_not_alert():
    d = drive(ROUTE, trip_id="t", noise_m=4.0, seed=1)
    rows = [dict(r) for r in d.rows]
    rows[80]["lat"] += 0.002          # one fix ~220 m away, then back to normal
    assert replay(ROUTE, rows) == []


def test_poor_reported_accuracy_widens_the_threshold():
    # Car 30 m off the route, but the phone says its accuracy is 50 m: not provably off.
    path = path_from_legs((START[0] + 30 / 111_195, START[1]), [(90, 2000)])
    d = drive(path, trip_id="t", noise_m=0, seed=1)
    rows = [dict(r, accuracy=50.0) for r in d.rows]
    assert replay(ROUTE, rows) == []
    # With good accuracy the same drive is a real deviation.
    good = [dict(r, accuracy=5.0) for r in d.rows]
    assert len(offs(replay(ROUTE, good))) == 1


# -- wrong turns are flagged in time ---------------------------------------------
@pytest.mark.parametrize("turn_bearing", [180, 0, 135])   # right turn, left turn, sharp-ish fork
def test_wrong_turn_flagged_within_two_seconds_of_certain(turn_bearing):
    taken = path_from_legs(START, [(90, 1000), (turn_bearing, 1000)])
    latencies = []
    for seed in SEEDS:
        d = drive(taken, trip_id="t", noise_m=4.0, seed=seed)
        certain = t_of(first_time_off_route(d, ROUTE, threshold_m=40.0))
        left = t_of(first_left_route(d, ROUTE))
        events = replay(ROUTE, d.rows)
        assert len(offs(events)) == 1, f"seed {seed}: {events}"
        alert = t_of(offs(events)[0].ts)
        assert alert <= certain + 2.0, f"seed {seed}: alert {alert - certain:+.1f}s vs certain"
        assert alert >= left, f"seed {seed}: alerted before the car left the route"
        latencies.append(alert - certain)
    print(f"turn {turn_bearing}: alert vs certain, min {min(latencies):+.1f}s max {max(latencies):+.1f}s")


def test_off_route_event_carries_contract_fields():
    taken = path_from_legs(START, [(90, 1000), (180, 1000)])
    d = drive(taken, trip_id="t", seed=1)
    ev = offs(replay(ROUTE, d.rows))[0]
    assert ev.data["reason"] == "distance"
    assert ev.data["recovery"]["action"] == "reroute"
    assert ev.data["deviation_m"] > 20
    assert 0 < ev.data["confidence"] <= 1


# -- driving the wrong way along the same road -----------------------------------------
def test_reversing_direction_on_the_route_is_caught_by_heading():
    # East 500 m (50 s), then straight back west along the same road.
    taken = path_from_legs(START, [(90, 500), (270, 500)])
    for seed in SEEDS:
        d = drive(taken, trip_id="t", noise_m=4.0, seed=seed)
        t_turn = t_of(d.rows[0]) + 50.0
        events = replay(ROUTE, d.rows)
        assert len(offs(events)) == 1, f"seed {seed}"
        alert = t_of(offs(events)[0].ts)
        assert t_turn <= alert <= t_turn + 7.5, f"seed {seed}: alert {alert - t_turn:+.1f}s after reversing"
        assert offs(events)[0].data["reason"] == "heading"


def test_slow_creep_backwards_heading_is_ignored():
    # Below the minimum speed the heading is unreliable (GPS heading is noise when stopped).
    d = drive(ROUTE, trip_id="t", noise_m=0, seed=1)
    rows = [dict(r, heading=270.0, speed=0.5) for r in d.rows]
    assert replay(ROUTE, rows) == []


# -- recovery -----------------------------------------------------------------------
def test_wrong_turn_then_uturn_returns_to_route():
    # Wrong turn south for 300 m, U-turn, back north to the road, carry on east.
    taken = path_from_legs(START, [(90, 1000), (180, 300), (0, 300), (90, 600)])
    for seed in SEEDS:
        d = drive(taken, trip_id="t", noise_m=4.0, seed=seed)
        events = replay(ROUTE, d.rows)
        assert [e.event for e in events] == ["off_route", "back_on_route"], f"seed {seed}: {events}"
        t0 = t_of(d.rows[0])
        back = t_of(events[1].ts)
        # back at the junction at 100 + 30 + 30 = 160 s; confirmed a few seconds later
        assert 160.0 <= back - t0 <= 170.0, f"seed {seed}: back_on_route at {back - t0:.0f}s"


# -- robustness -----------------------------------------------------------------------
def test_gap_in_fixes_does_not_break_tracking():
    d = drive(ROUTE, trip_id="t", noise_m=4.0, seed=2)
    rows = d.rows[:60] + d.rows[120:]   # 60 s tunnel: the car moved 600 m unseen
    assert replay(ROUTE, rows) == []


def test_route_that_doubles_back_does_not_confuse_the_window():
    # A route that goes out 1 km east, loops north and comes back west alongside itself 150 m north.
    route = path_from_legs(START, [(90, 1000), (0, 150), (270, 1000)])
    for seed in range(10):
        d = drive(route, trip_id="t", noise_m=4.0, seed=seed)
        assert replay(route, d.rows) == [], f"false alarm with seed {seed}"


def test_detector_is_deterministic_and_validates_input():
    d = drive(ROUTE, trip_id="t", seed=3)
    assert replay(ROUTE, d.rows) == replay(ROUTE, d.rows)
    with pytest.raises(ValueError):
        WrongWayDetector([START])
    assert DetectorConfig().confirm_s == 1.0
