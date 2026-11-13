"""The Valhalla client, against a fake transport (no server needed)."""

from engine.valhalla import fetch_bundle

def encode(points, precision=6):
    f, out, plat, plon = 10 ** precision, [], 0, 0
    for lat, lon in points:
        for new, old in ((round(lat * f), plat), (round(lon * f), plon)):
            d = new - old
            d = ~(d << 1) if d < 0 else d << 1
            while d >= 0x20:
                out.append(chr((0x20 | (d & 0x1F)) + 63))
                d >>= 5
            out.append(chr(d + 63))
        plat, plon = round(lat * f), round(lon * f)
    return "".join(out)


class FakeValhalla:
    def __init__(self):
        self.calls = []
        self.shape = [(12.0, 77.0), (12.001, 77.0), (12.002, 77.0)]

    def __call__(self, path, body):
        self.calls.append(path)
        if path == "route":
            return {"trip": {"legs": [{
                "shape": encode(self.shape), "summary": {"length": 0.222},
                "maneuvers": [
                    {"type": 1, "begin_shape_index": 0, "instruction": "Drive north.", "length": 0.111},
                    {"type": 23, "begin_shape_index": 1, "instruction": "Keep right to take Test Flyover.",
                     "length": 0.111, "street_names": ["Test Flyover"]}]}]}}
        if path == "trace_attributes":
            return {"edges": [
                {"begin_shape_index": 0, "end_shape_index": 1, "names": ["Main Road"], "use": "road",
                 "road_class": "primary", "length": 0.111, "way_id": 1},
                {"begin_shape_index": 1, "end_shape_index": 2, "names": ["Test Flyover"], "use": "road",
                 "road_class": "motorway", "length": 0.111, "way_id": 2, "bridge": True}]}
        if path == "locate":
            def e(names, way, pct):
                return {"percent_along": pct, "edge_info": {"names": names, "way_id": way},
                        "edge": {"classification": {"use": "road", "classification": "primary"},
                                 "bridge": False, "geo_attributes": {"length": 100}}}
            return [{"edges": [e(["Test Flyover"], 2, 0.0), e(["Main Road"], 3, 0.0), e(["Main Road"], 1, 1.0)]}]
        raise AssertionError(path)


def test_bundle_collects_route_edges_and_only_outgoing_alternatives():
    fake = FakeValhalla()
    b = fetch_bundle(fake, (12.0, 77.0), (12.002, 77.0))

    assert fake.calls == ["route", "trace_attributes", "locate"]
    assert b["route"] == [[12.0, 77.0], [12.001, 77.0], [12.002, 77.0]]
    assert b["length_m"] == 222.0
    assert [e["names"] for e in b["edges"]] == [["Main Road"], ["Test Flyover"]]
    assert b["edges"][1]["bridge"] is True and b["edges"][1]["length_m"] == 111.0
    # the route's own edge (way 2) and the road we arrived on (pct 1.0) are excluded
    assert [a["way_id"] for a in b["forks"]["1"]] == [3]
