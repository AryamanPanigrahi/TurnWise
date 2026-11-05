"""Convert internal units (metres, seconds) into spoken quantities.

Per CLAUDE.md conventions, unit conversion happens only at the voice layer.
Rounding is deliberately coarse: a driver needs "300 metres", not "287 metres".
"""

from __future__ import annotations

import math
from typing import Mapping


def round_distance_m(distance_m: float) -> int:
    """Round a distance to a driver-friendly value in metres.

    < 100 m  -> nearest 10 m (minimum 10)
    < 1000 m -> nearest 50 m
    otherwise -> nearest 100 m
    """
    if distance_m < 0:
        raise ValueError("distance_m must be >= 0")
    if distance_m < 100:
        return max(10, int(round(distance_m / 10.0)) * 10)
    if distance_m < 1000:
        return int(round(distance_m / 50.0)) * 50
    return int(round(distance_m / 100.0)) * 100


def _fmt_number(x: float) -> str:
    """1.0 -> '1', 1.25 -> '1.2' (one decimal, trailing .0 dropped)."""
    s = f"{x:.1f}"
    return s[:-2] if s.endswith(".0") else s


def format_distance(distance_m: float, units: Mapping[str, str]) -> str:
    """Format metres using a language's unit templates, e.g. {'m': '{n} metres', 'km': '{n} km'}."""
    rounded = round_distance_m(distance_m)
    if rounded >= 1000:
        return units["km"].format(n=_fmt_number(rounded / 1000.0))
    return units["m"].format(n=rounded)


def format_duration(seconds: float, units: Mapping[str, str]) -> str:
    """Format seconds as minutes (rounded up, minimum 1) or hours + minutes."""
    if seconds < 0:
        raise ValueError("seconds must be >= 0")
    minutes = max(1, math.ceil(seconds / 60.0))
    if minutes < 60:
        return units["min"].format(n=minutes)
    hours, rem = divmod(minutes, 60)
    hour_txt = units["hour"].format(n=hours)
    if rem == 0:
        return hour_txt
    return units["hour_min"].format(h=hour_txt, m=units["min"].format(n=rem))
