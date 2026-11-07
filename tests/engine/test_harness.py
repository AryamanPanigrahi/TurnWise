"""Scoring rules of the replay harness, on hand-made events (no detector involved)."""

from engine.harness import format_report, score
from engine.synthetic import drive, path_from_legs
from engine.wrong_way import Event

T0 = "2026-11-07T04:40:00.000Z"


def ts(offset_s: float) -> str:
    s = 40 * 60 + offset_s
    return f"2026-11-07T04:{int(s // 60):02d}:{s % 60:06.3f}Z"


def exp(*events, clean=False):
    return {"clean": clean, "events": list(events)}


def off(at, **kw):
    return {"event": "off_route", "ts": ts(at), **kw}


def got(kind, at):
    return Event(kind, ts(at))


def test_alert_inside_window_passes_and_reports_latency():
    r = score("t", exp(off(10)), [got("off_route", 11.5)])
    assert r.passed and r.latencies == [("off_route", 1.5)]


def test_alert_more_than_two_seconds_late_fails():
    r = score("t", exp(off(10)), [got("off_route", 12.5)])
    assert not r.passed
    assert any("MISSED off_route" in p for p in r.problems)
    assert any("FALSE ALARM" in p for p in r.problems)   # the late one is also unexplained


def test_alert_far_too_early_fails():
    r = score("t", exp(off(10)), [got("off_route", 3)])    # 7 s early, default window is 5 s
    assert not r.passed


def test_early_alert_inside_window_passes():
    assert score("t", exp(off(10)), [got("off_route", 6)]).passed


def test_missed_wrong_turn_fails():
    r = score("t", exp(off(10)), [])
    assert not r.passed and "engine raised none" in r.problems[0]


def test_false_alarm_on_clean_drive_fails():
    r = score("t", exp(clean=True), [got("off_route", 30)])
    assert not r.passed
    assert any("FALSE ALARM" in p for p in r.problems)
    assert any("clean drive" in p for p in r.problems)


def test_clean_drive_with_no_events_passes():
    assert score("t", exp(clean=True), []).passed


def test_per_event_tolerance_overrides_the_default():
    e = exp(off(10, early_s=0, late_s=7.5))
    assert score("t", e, [got("off_route", 16)]).passed
    assert not score("t", e, [got("off_route", 9)]).passed


def test_each_detector_event_explains_at_most_one_expected_event():
    r = score("t", exp(off(10), off(11)), [got("off_route", 11)])
    assert not r.passed   # one alert cannot satisfy two wrong turns


def test_unsupported_events_are_skipped_not_failed():
    e = exp({"event": "decision_point_ahead", "ts": ts(5)}, {"event": "arrived", "ts": ts(50)}, clean=True)
    r = score("t", e, [])
    assert r.passed and len(r.skipped) == 2


def test_unexpected_back_on_route_is_reported():
    r = score("t", exp(), [got("back_on_route", 20)])
    assert not r.passed and "UNEXPECTED" in r.problems[0]


def test_report_lists_failures_and_totals():
    bad = score("bad", exp(off(10)), [])
    good = score("good", exp(clean=True), [])
    text = format_report([bad, good], ["real_drive.jsonl (missing real_drive.route.json)"])
    assert "FAIL  bad" in text and "PASS  good" in text and "SKIP  real_drive" in text
    assert "1/2 traces passed" in text


def test_generated_headings_stay_inside_the_contract_range():
    # Regression: round(359.96, 1) used to give 360.0, which the gps contract forbids.
    route = path_from_legs((12.9756, 77.6066), [(0, 3000)])   # due north: headings sit near 0/360
    d = drive(route, trip_id="t", noise_m=0, heading_noise_deg=2.0, seed=1)
    assert all(0 <= r["heading"] < 360 for r in d.rows)
