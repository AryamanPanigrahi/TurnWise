import json

from tools import gpx_to_trace, trace_check
from tools.trace_format import (bearing_deg, check_expected, check_points, convert,
                                dumps_jsonl, haversine_m, loads_jsonl, parse_ts)

# ~11 m north per step (0.0001° lat), 1 Hz, starting near MG Road.
LAT0, LON0 = 12.9757, 77.6061


def gpx(n=30, step=0.0001, extras="", t0=0):
    pts = "".join(
        f'<trkpt lat="{LAT0 + i * step:.6f}" lon="{LON0}"><ele>900</ele>'
        f"<time>2026-11-07T04:30:{(t0 + i) % 60:02d}Z</time>{extras}</trkpt>"
        for i in range(n))
    return ('<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><trkseg>{pts}</trkseg></trk></gpx>")


def test_geometry():
    d = haversine_m(LAT0, LON0, LAT0 + 0.001, LON0)
    assert 110 < d < 112
    assert abs(bearing_deg(LAT0, LON0, LAT0 + 0.001, LON0) - 0) < 0.01
    assert abs(bearing_deg(LAT0, LON0, LAT0, LON0 + 0.001) - 90) < 0.1


def test_gpx_converts_to_contract_points_with_derived_motion():
    pts = convert(gpx(), "gpx", "trp_1")
    assert len(pts) == 30
    p = pts[5]
    assert p.trip_id == "trp_1" and p.ts == "2026-11-07T04:30:05.000Z"
    assert 10.5 < p.speed < 11.6 and p.heading == 0.0
    assert pts[0].speed is None  # nothing before the first fix
    rows = loads_jsonl(dumps_jsonl(pts))
    assert set(rows[0]) == {"trip_id", "ts", "lat", "lon", "speed", "heading", "accuracy"}
    assert check_points(rows).errors == []


def test_logger_speed_and_course_are_kept_from_extensions():
    ext = "<extensions><speed>9.5</speed><course>12.0</course><accuracy>4</accuracy></extensions>"
    p = convert(gpx(n=3, extras=ext), "gpx", "t")[1]
    assert (p.speed, p.heading, p.accuracy) == (9.5, 12.0, 4.0)


def test_stationary_points_have_null_heading():
    pts = convert(gpx(n=5, step=0.0), "gpx", "t")
    assert all(p.heading is None for p in pts)
    assert pts[1].speed == 0.0


def test_duplicates_dropped_and_sorted():
    text = gpx(n=5)
    # duplicate the 3rd point and move the 1st to the end
    seg_start = text.index("<trkpt")
    trkpts = text[seg_start:text.index("</trkseg>")].split("</trkpt>")[:-1]
    shuffled = trkpts[1:] + [trkpts[2], trkpts[0]]
    text = text[:seg_start] + "</trkpt>".join(shuffled) + "</trkpt></trkseg></trk></gpx>"
    pts = convert(text, "gpx", "t")
    assert [p.ts[17:19] for p in pts] == ["00", "01", "02", "03", "04"]


def test_trim_ends_hides_start_and_end():
    pts = convert(gpx(n=60), "gpx", "t", trim_start_m=100, trim_end_m=100)
    assert len(pts) < 60 - 16
    assert haversine_m(LAT0, LON0, pts[0].lat, pts[0].lon) > 100
    assert convert(gpx(n=60), "gpx", "t", 0, 0)[0].lat == LAT0


def test_csv_reader():
    csv = ("time,lat,lon,elevation,accuracy,bearing,speed\n"
           f"2026-11-07T04:30:00Z,{LAT0},{LON0},900,5,,\n"
           f"2026-11-07T04:30:01Z,{LAT0 + 0.0001},{LON0},900,5,3,11.0\n")
    pts = convert(csv, "csv", "t")
    assert pts[1].speed == 11.0 and pts[1].heading == 3.0 and pts[1].accuracy == 5.0


def test_naive_times_are_utc():
    assert parse_ts("2026-11-07T04:30:00").isoformat() == "2026-11-07T04:30:00+00:00"
    assert parse_ts("2026-11-07T10:00:00+05:30").hour == 4


def test_check_flags_bad_rows_gaps_and_glitches():
    rows = loads_jsonl(dumps_jsonl(convert(gpx(n=10), "gpx", "t")))
    bad = [dict(rows[0], ts="2026-11-07 04:30:00"), dict(rows[1], heading=360)]
    assert len(check_points(bad).errors) == 2
    gap = rows[:3] + [dict(rows[3], ts="2026-11-07T04:30:20.000Z")]
    assert any("gap" in w for w in check_points(gap).warnings)
    jump = rows[:3] + [dict(rows[3], lat=LAT0 + 0.01)]
    assert any("jump" in w for w in check_points(jump).warnings)
    assert check_points([]).errors == ["trace is empty"]


def test_check_expected():
    rows = loads_jsonl(dumps_jsonl(convert(gpx(n=10), "gpx", "t")))
    ok = {"clean": False, "events": [{"event": "off_route", "ts": "2026-11-07T04:30:05Z"}]}
    assert check_expected(ok, rows) == []
    assert check_expected({"clean": True, "events": ok["events"]}, rows)
    outside = {"clean": False, "events": [{"event": "off_route", "ts": "2026-11-07T05:00:00Z"}]}
    assert "outside" in check_expected(outside, rows)[0]
    assert check_expected({"clean": False, "events": [{"event": "nope", "ts": rows[0]["ts"]}]}, rows)


def test_cli_round_trip(tmp_path, capsys):
    src = tmp_path / "drive.gpx"
    src.write_text(gpx(n=60), encoding="utf-8")
    dst = tmp_path / "traces" / "2026-11-07_test_01.jsonl"
    assert gpx_to_trace.main([str(src), str(dst), "--trim-start-m", "50", "--trim-end-m", "50"]) == 0
    exp = json.loads(dst.with_suffix(".expected.json").read_text())
    assert exp["trace"] == dst.name and exp["events"] == [] and exp["clean"] is False
    assert loads_jsonl(dst.read_text())[0]["trip_id"] == "trace_2026-11-07_test_01"
    assert trace_check.main([str(dst)]) == 0
    dst.with_suffix(".expected.json").unlink()
    assert trace_check.main([str(dst)]) == 1
    assert gpx_to_trace.main([str(src), str(tmp_path / "x.txt")]) == 2
