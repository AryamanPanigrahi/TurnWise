"""Decode Valhalla/Google encoded polylines. Pure, standard library only."""

from __future__ import annotations

from engine.geometry import LatLon


def decode_polyline(encoded: str, precision: int = 6) -> list[LatLon]:
    """Decode an encoded polyline into (lat, lon) pairs.

    Valhalla uses precision 6 (the default here); Google's classic format is 5.
    """
    factor = 10 ** precision
    points: list[LatLon] = []
    i = lat = lon = 0
    while i < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[i]) - 63
                i += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lon += delta
        points.append((lat / factor, lon / factor))
    return points
