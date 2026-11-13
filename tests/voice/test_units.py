from voice.units import format_distance, format_duration, round_distance_m

EN = {"m": "{n} metres", "km": "{n} km", "min": "{n} min", "hour": "{n} h", "hour_min": "{h} {m}"}


def test_round_distance():
    cases = [(0, 10), (4, 10), (37, 40), (99, 100), (120, 100), (287, 300),
             (974, 950), (980, 1000), (1249, 1200), (12345, 12300)]
    for given, expected in cases:
        assert round_distance_m(given) == expected, given


def test_format_distance_switches_to_km():
    assert format_distance(287, EN) == "300 metres"
    assert format_distance(980, EN) == "1 km"
    assert format_distance(1260, EN) == "1.3 km"


def test_format_duration():
    assert format_duration(0, EN) == "1 min"
    assert format_duration(61, EN) == "2 min"
    assert format_duration(3600, EN) == "1 h"
    assert format_duration(3600 + 25 * 60, EN) == "1 h 25 min"


def test_negative_rejected():
    for fn, arg in ((round_distance_m, -1), (lambda s: format_duration(s, EN), -1)):
        try:
            fn(arg)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")
