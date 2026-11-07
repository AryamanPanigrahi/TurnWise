import pytest

from engine.geometry import (
    bearing_deg,
    destination,
    haversine_m,
    heading_diff_deg,
    project_to_polyline,
)

MG_ROAD = (12.9756, 77.6066)


def test_haversine_one_degree_of_latitude():
    assert haversine_m((12.0, 77.0), (13.0, 77.0)) == pytest.approx(111_195, abs=50)


def test_haversine_zero_and_symmetric():
    a, b = MG_ROAD, (12.8456, 77.6603)
    assert haversine_m(a, a) == 0
    assert haversine_m(a, b) == pytest.approx(haversine_m(b, a))


@pytest.mark.parametrize(
    "b, expected",
    [((13.0, 77.0), 0), ((11.0, 77.0), 180), ((12.0, 77.5), 90), ((12.0, 76.5), 270)],
)
def test_bearing_cardinal_directions(b, expected):
    assert heading_diff_deg(bearing_deg((12.0, 77.0), b), expected) < 0.5


@pytest.mark.parametrize(
    "h1, h2, expected",
    [(350, 10, 20), (10, 350, 20), (0, 180, 180), (90, 90, 0), (359, 1, 2), (270, 90, 180)],
)
def test_heading_diff_wraps_around(h1, h2, expected):
    assert heading_diff_deg(h1, h2) == pytest.approx(expected)


def test_destination_round_trip():
    end = destination(MG_ROAD, 45.0, 1000.0)
    assert haversine_m(MG_ROAD, end) == pytest.approx(1000.0, abs=0.5)
    assert heading_diff_deg(bearing_deg(MG_ROAD, end), 45.0) < 0.1


def test_project_point_beside_a_straight_road():
    # A road running due east for 1 km; a point 30 m north of its midpoint.
    start = MG_ROAD
    end = destination(start, 90.0, 1000.0)
    point = destination(destination(start, 90.0, 500.0), 0.0, 30.0)

    proj = project_to_polyline(point, [start, end])

    assert proj.distance_m == pytest.approx(30.0, abs=0.5)
    assert proj.along_m == pytest.approx(500.0, abs=1.0)
    assert proj.segment_index == 0
    assert heading_diff_deg(proj.bearing_deg, 90.0) < 0.5


def test_project_clamps_to_the_ends():
    start = MG_ROAD
    end = destination(start, 90.0, 1000.0)
    behind = destination(start, 270.0, 200.0)  # 200 m behind the start

    proj = project_to_polyline(behind, [start, end])

    assert proj.along_m == pytest.approx(0.0, abs=0.5)
    assert proj.distance_m == pytest.approx(200.0, abs=1.0)


def test_project_picks_nearest_segment_and_accumulates_distance():
    # East 1 km, then north 1 km (an L-shaped road).
    a = MG_ROAD
    b = destination(a, 90.0, 1000.0)
    c = destination(b, 0.0, 1000.0)
    point = destination(destination(b, 0.0, 400.0), 270.0, 10.0)  # 10 m west of the north leg

    proj = project_to_polyline(point, [a, b, c])

    assert proj.segment_index == 1
    assert proj.along_m == pytest.approx(1400.0, abs=2.0)
    assert proj.distance_m == pytest.approx(10.0, abs=0.5)
    assert heading_diff_deg(proj.bearing_deg, 0.0) < 0.5


def test_project_rejects_a_single_point():
    with pytest.raises(ValueError):
        project_to_polyline(MG_ROAD, [MG_ROAD])
