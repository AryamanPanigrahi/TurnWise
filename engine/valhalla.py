"""Valhalla client: fetch a route and everything the engine needs, as one JSON "bundle".

This is the ONLY engine module that touches the network, and it is kept thin:
all decisions live in the pure modules (decision_points.py, wrong_way.py).
Run it once per route and commit the bundle; tests then replay the saved file.

    python -m engine.valhalla --origin 12.9757,77.6061 --dest 12.8456,77.6603 \\
        --out tests/fixtures/routes/mgroad-ecity.bundle.json

Bundle format (also a valid `<trace>.route.json`, which only reads "route"):

    {
      "source": "valhalla",
      "route":   [[lat, lon], ...],                       # the planned polyline
      "length_m": 17852.0,
      "maneuvers": [{"type", "begin_shape_index", "instruction", "street_names", "length_m"}],
      "edges":     [{"begin_shape_index", "end_shape_index", "names", "use", "road_class",
                     "bridge", "tunnel", "toll", "way_id", "lane_count", "length_m"}],
      "forks":     {"<shape_index>": [ other roads leaving that node, same fields + percent_along ]}
    }

`forks` is only filled for candidate decision nodes: fork-type manoeuvres and the
places where the route climbs onto a flyover or dives into an underpass.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Callable, Mapping

from engine.decision_points import FORK_TYPES, is_elevated, is_underpass
from engine.polyline import decode_polyline

# A transport posts JSON to a Valhalla endpoint and returns the parsed JSON reply.
Transport = Callable[[str, Mapping], object]

EDGE_ATTRIBUTES = [
    "edge.names", "edge.road_class", "edge.use", "edge.length", "edge.bridge", "edge.tunnel",
    "edge.toll", "edge.way_id", "edge.lane_count", "edge.begin_shape_index", "edge.end_shape_index",
]


def http_transport(base_url: str = "http://localhost:8002", timeout_s: float = 120.0) -> Transport:
    def post(path: str, body: Mapping) -> object:
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/{path}", json.dumps(body).encode(),
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.load(resp)
    return post


def _edge(e: Mapping) -> dict:
    return {
        "begin_shape_index": e["begin_shape_index"], "end_shape_index": e["end_shape_index"],
        "names": e.get("names") or [], "use": e.get("use"), "road_class": e.get("road_class"),
        "bridge": bool(e.get("bridge")), "tunnel": bool(e.get("tunnel")), "toll": bool(e.get("toll")),
        "way_id": e.get("way_id"), "lane_count": e.get("lane_count"),
        "length_m": round(e["length"] * 1000, 1),
    }


def _located_alternatives(locate_reply: object, route_way_id: int | None) -> list[dict]:
    """Roads that LEAVE the located node (percent_along == 0), other than the route's own."""
    out = []
    for e in locate_reply[0].get("edges", []):
        if e.get("percent_along") != 0.0:
            continue  # ends at this node: the road we arrived on (or its twin)
        info, edge = e["edge_info"], e["edge"]
        if route_way_id is not None and info.get("way_id") == route_way_id:
            continue
        cls = edge.get("classification", {})
        out.append({
            "names": info.get("names") or [], "way_id": info.get("way_id"),
            "use": cls.get("use"), "road_class": cls.get("classification"),
            "bridge": bool(edge.get("bridge")), "tunnel": bool(edge.get("tunnel")),
            "toll": bool(edge.get("toll")), "percent_along": e["percent_along"],
            "length_m": edge.get("geo_attributes", {}).get("length"),
        })
    return out


def fetch_bundle(post: Transport, origin: tuple[float, float], dest: tuple[float, float],
                 costing: str = "auto") -> dict:
    """Ask Valhalla for a route and gather edges and fork alternatives."""
    reply = post("route", {
        "locations": [{"lat": origin[0], "lon": origin[1]}, {"lat": dest[0], "lon": dest[1]}],
        "costing": costing, "directions_options": {"units": "kilometers"}})
    leg = reply["trip"]["legs"][0]
    shape = decode_polyline(leg["shape"])

    trace = post("trace_attributes", {
        "shape": [{"lat": a, "lon": b} for a, b in shape], "costing": costing,
        "shape_match": "edge_walk",
        "filters": {"attributes": EDGE_ATTRIBUTES, "action": "include"}})
    edges = [_edge(e) for e in trace["edges"]]

    maneuvers = [{
        "type": m["type"], "begin_shape_index": m["begin_shape_index"],
        "instruction": m.get("instruction"), "street_names": m.get("street_names") or [],
        "length_m": round(m["length"] * 1000, 1)} for m in leg["maneuvers"]]

    # Candidate decision nodes: fork-type manoeuvres, and flyover / underpass entries.
    candidates = {m["begin_shape_index"] for m in maneuvers if m["type"] in FORK_TYPES}
    for prev, cur in zip(edges, edges[1:]):
        if (is_elevated(cur) and not is_elevated(prev)) or (is_underpass(cur) and not is_underpass(prev)):
            candidates.add(cur["begin_shape_index"])

    forks: dict[str, list[dict]] = {}
    for idx in sorted(candidates):
        route_edge = next((e for e in edges if e["begin_shape_index"] == idx), None)
        lat, lon = shape[idx]
        located = post("locate", {"locations": [{"lat": lat, "lon": lon}], "costing": costing, "verbose": True})
        forks[str(idx)] = _located_alternatives(located, route_edge["way_id"] if route_edge else None)

    return {
        "source": "valhalla",
        "route": [[round(a, 6), round(b, 6)] for a, b in shape],
        "length_m": round(leg["summary"]["length"] * 1000, 1),
        "maneuvers": maneuvers, "edges": edges, "forks": forks,
    }


def _latlon(text: str) -> tuple[float, float]:
    a, b = text.split(",")
    return float(a), float(b)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Save a Valhalla route bundle to a JSON file.")
    ap.add_argument("--origin", required=True, type=_latlon, help="lat,lon")
    ap.add_argument("--dest", required=True, type=_latlon, help="lat,lon")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--url", default="http://localhost:8002")
    a = ap.parse_args(argv)
    bundle = fetch_bundle(http_transport(a.url), a.origin, a.dest)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(bundle, indent=1) + "\n", encoding="utf-8")
    print(f"saved {a.out}: {len(bundle['route'])} points, {len(bundle['edges'])} edges, "
          f"{len(bundle['forks'])} candidate forks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
