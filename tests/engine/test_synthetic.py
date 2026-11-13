import json
import math
import statistics

import pytest

from engine.geometry import haversine_m, heading_diff_deg, project_to_polyline
from engine.synthetic import (
    drive,
    expected_events,
    first_time_off_route,
    path_from_legs,
    write_trace,
)
from tools.trace_format import check_expected, check_points, loads_jsonl, parse_ts

START = (12.9756, 77.6066)
ROUTE = path_from_legs(START, [(90, 2000)])                    # 2 km due east
WRONG = path_from_legs(START, [(90, 1000), (180, 1000)])       # east 1 km, then south


def test_same_seed_gives_identical_trace():
    a = drive(ROUTE, trip_id="t", seed=7)
    b = drive(ROUTE, trip_id="t", seed=7)
    c = drive(ROUTE, trip_id="t", seed=8)
    assert a.rows == b.rows
    assert a.rows != c.rows


def test_one_fix_per_second_at_requested_speed():
    d = drive(ROUTE, trip_id="t", speed_mps=10.0, noise_m=0)
    assert len(d.rows) == 201          # 2000 m at 10 m/s, plus the first fix
    times = [parse_ts(r["ts"]).timestamp() for r in d.rows]
    assert all(b - a == pytest.approx(1.0) for a, b in zip(times, times[1:]))
    step = haversine_m(d.truth[0], d.truth[1])
    assert step == pytest.approx(10.0, abs=0.05)


def test_zero_noise_trace_sits_on_the_route():
    d = drive(ROUTE, trip_id="t", noise_m=0)
    worst = max(project_to_polyline((r["lat"], r["lon"]), ROUTE).distance_m for r in d.rows)
    assert worst < 0.5


def test_noise_has_roughly_the_requested_size():
    d = drive(ROUTE, trip_id="t", noise_m=4.0, seed=3)
    errors = [haversine_m((r["lat"], r["lon"]), p) for r, p in zip(d.rows, d.truth)]
    # Error distance of 2-D gaussian noise with sigma 4 m has mean ~ 4 * sqrt(pi/2) = 5.0 m
    assert statistics.mean(errors) == pytest.approx(5.0, abs=1.0)


def test_heading_follows_the_road_and_turns_with_it():
    d = drive(WRONG, trip_id="t", noise_m=0, heading_noise_deg=0)
    assert d.rows[10]["heading"] == pytest.approx(90.0, abs=0.5)
    assert d.rows[-1]["heading"] == pytest.approx(180.0, abs=0.5)


def test_clean_drive_has_no_off_route_event():
    d = drive(ROUTE, trip_id="t", seed=1)
    exp = expected_events(d, ROUTE, name="clean")
    assert exp["clean"] is True
    assert exp["events"] == []


def test_wrong_turn_becomes_certain_just_after_the_junction():
    d = drive(WRONG, trip_id="t", seed=1)
    ts = first_time_off_route(d, ROUTE, threshold_m=40.0)
    assert ts is not None
    t0 = parse_ts(d.rows[0]["ts"]).timestamp()
    elapsed = parse_ts(ts).timestamp() - t0
    # junction at 100 s (1000 m at 10 m/s); 40 m south of the road is reached at ~104 s
    assert elapsed == pytest.approx(104.0, abs=1.0)


def test_generated_files_pass_ram_trace_checks(tmp_path):
    d = drive(WRONG, trip_id="synthetic_wrong_turn_01", seed=1)
    exp = expected_events(d, ROUTE, name="synthetic_wrong_turn_01", notes="test")
    write_trace(tmp_path, "synthetic_wrong_turn_01", d, exp)

    rows = loads_jsonl((tmp_path / "synthetic_wrong_turn_01.jsonl").read_text(encoding="utf-8"))
    loaded = json.loads((tmp_path / "synthetic_wrong_turn_01.expected.json").read_text(encoding="utf-8"))

    report = check_points(rows)
    assert report.errors == []
    assert check_expected(loaded, rows) == []
    assert loaded["clean"] is False
    assert [e["event"] for e in loaded["events"]] == ["off_route"]


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        drive([START], trip_id="t")
    with pytest.raises(ValueError):
        drive(ROUTE, trip_id="t", speed_mps=0)
