"""The HTTP/WebSocket API, end to end, on the real saved route and synthetic GPS."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app
from backend.settings import Settings
from engine.geometry import bearing_deg, destination, haversine_m
from engine.synthetic import drive

BUNDLE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "routes"
                     / "mgroad-ecity.bundle.json").read_text(encoding="utf-8"))
ROUTE = [tuple(p) for p in BUNDLE["route"]]
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"origin": {"lat": 12.9757, "lon": 77.6061}, "destination": {"lat": 12.8456, "lon": 77.6603}}


def make_client(provider=None):
    app = create_app(Settings(api_token=TOKEN), route_provider=provider or (lambda o, d: BUNDLE))
    return TestClient(app)


@pytest.fixture()
def client():
    with make_client() as c:
        yield c


@pytest.fixture()
def trip(client):
    r = client.post("/v1/trips", json=BODY, headers=AUTH)
    assert r.status_code == 201
    return r.json()["trip_id"]


def fixes(trip_id, path=ROUTE, seed=1, speed=15.0):
    rows = drive(path, trip_id=trip_id, speed_mps=speed, noise_m=4.0, seed=seed).rows
    return rows


def post_gps(client, rows, headers=AUTH):
    return client.post("/v1/gps", json={"points": rows}, headers=headers)


# -- startup and auth -------------------------------------------------------------------------
def test_server_refuses_to_start_without_a_token():
    with pytest.raises(RuntimeError, match="TURNWISE_API_TOKEN"):
        create_app(Settings(api_token=None))


@pytest.mark.parametrize("method, path", [("post", "/v1/trips"), ("post", "/v1/gps"), ("post", "/v1/ask"),
                                          ("post", "/v1/trips/x/end")])
def test_every_endpoint_needs_the_token(client, method, path):
    assert getattr(client, method)(path, json={}).status_code == 401
    bad = getattr(client, method)(path, json={}, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401


def test_healthz_is_open(client):
    assert client.get("/healthz").json() == {"ok": True}


# -- trips ----------------------------------------------------------------------------------------
def test_create_trip_returns_an_unguessable_id_and_route_summary(client):
    r = client.post("/v1/trips", json=BODY, headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["trip_id"].startswith("trp_") and len(body["trip_id"]) >= 20
    assert body["length_m"] == pytest.approx(BUNDLE["length_m"])
    assert body["decision_points"] >= 5


def test_routing_failure_is_a_502_without_leaking_details():
    def broken(o, d):
        raise ConnectionError("valhalla at 10.0.0.5 is down")

    with make_client(broken) as c:
        r = c.post("/v1/trips", json=BODY, headers=AUTH)
    assert r.status_code == 502 and "10.0.0.5" not in r.text


def test_trip_request_is_validated(client):
    bad = {"origin": {"lat": 120, "lon": 77}, "destination": {"lat": 12, "lon": 77}}
    assert client.post("/v1/trips", json=bad, headers=AUTH).status_code == 422


# -- GPS ingest ---------------------------------------------------------------------------------
def test_gps_batch_is_accepted(client, trip):
    r = post_gps(client, fixes(trip)[:30])
    assert r.status_code == 202
    assert r.json() == {"accepted": 30, "duplicates": 0, "late": 0}


def test_unknown_trip_is_403_and_ended_trip_is_409(client, trip):
    assert post_gps(client, fixes("trp_unknown")[:3]).status_code == 403
    assert client.post(f"/v1/trips/{trip}/end", headers=AUTH).status_code == 204
    assert post_gps(client, fixes(trip)[:3]).status_code == 409
    ask = client.post("/v1/ask", json={"trip_id": trip, "intent": "eta"}, headers=AUTH)
    assert ask.status_code == 409


def test_duplicates_and_out_of_order_points_are_handled(client, trip):
    rows = fixes(trip)[:20]
    shuffled = list(reversed(rows[:10])) + rows[10:]
    assert post_gps(client, shuffled).json() == {"accepted": 20, "duplicates": 0, "late": 0}
    again = post_gps(client, rows[5:15]).json()
    assert again == {"accepted": 0, "duplicates": 10, "late": 0}


def test_points_older_than_already_processed_ones_are_late_not_fed_to_the_engine(client, trip):
    rows = fixes(trip)
    post_gps(client, rows[10:20])
    r = post_gps(client, rows[0:5]).json()          # older than anything processed
    assert r == {"accepted": 5, "duplicates": 0, "late": 5}


@pytest.mark.parametrize("patch", [
    {"ts": "2026-11-07T04:30:00+05:30"},     # not UTC "Z"
    {"ts": "not a time"},
    {"lat": 91.0}, {"lon": -181.0},
    {"heading": 360.0}, {"speed": -1.0}, {"accuracy": -3.0},
])
def test_invalid_points_are_422(client, trip, patch):
    row = {**fixes(trip)[0], **patch}
    assert post_gps(client, [row]).status_code == 422


def test_batch_limits_and_mixed_trips_are_422(client, trip):
    rows = fixes(trip)
    assert client.post("/v1/gps", json={"points": []}, headers=AUTH).status_code == 422
    assert post_gps(client, (rows * 3)[:601]).status_code == 422
    mixed = [rows[0], {**rows[1], "trip_id": "trp_other"}]
    assert post_gps(client, mixed).status_code == 422


def test_unknown_fields_are_ignored_and_nulls_are_allowed(client, trip):
    row = {**fixes(trip)[0], "battery": 80, "speed": None, "heading": None, "accuracy": None}
    assert post_gps(client, [row]).status_code == 202


# -- ask -------------------------------------------------------------------------------------------
def test_ask_before_any_gps_is_not_sure(client, trip):
    r = client.post("/v1/ask", json={"trip_id": trip, "intent": "which_branch"}, headers=AUTH)
    assert r.status_code == 200 and r.json() == {"answer_key": "not_sure", "facts": {}}


def test_ask_near_the_flyover(client, trip):
    rows = fixes(trip)
    along_at_flyover = 8164
    n = int((along_at_flyover - 350) / 15)
    for i in range(0, n, 100):
        assert post_gps(client, rows[i:min(i + 100, n)]).status_code == 202
    r = client.post("/v1/ask", headers=AUTH, json={
        "trip_id": trip, "intent": "which_branch", "slots": {"options": ["flyover", "service_road"]}})
    body = r.json()
    assert body["answer_key"] == "which_branch.flyover"
    assert body["facts"]["distance_m"] == pytest.approx(350, abs=60)


def test_ask_rejects_unknown_intents(client, trip):
    r = client.post("/v1/ask", json={"trip_id": trip, "intent": "tell_a_joke"}, headers=AUTH)
    assert r.status_code == 422


# -- events websocket ---------------------------------------------------------------------------------
def collect_until(ws, stop_event):
    out = []
    while True:
        m = ws.receive_json()
        out.append(m)
        if m["event"] == stop_event:
            return out


def test_websocket_streams_a_whole_trip_in_order(client, trip):
    rows = fixes(trip)
    with client.websocket_connect(f"/v1/trips/{trip}/events", headers=AUTH) as ws:
        for i in range(0, len(rows), 200):
            assert post_gps(client, rows[i:i + 200]).status_code == 202
        events = collect_until(ws, "arrived")

    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert {e["event"] for e in events} == {"decision_point_ahead", "arrived"}
    arrived = events[-1]["data"]                      # events.md: arrived names the stop that was reached
    assert arrived["stop_id"] == f"stp_{trip.removeprefix('trp_')}_1" and arrived["distance_m"] <= 30
    assert all(e["trip_id"] == trip and e["ts"].endswith("Z") for e in events)
    flyover = [e for e in events if e["data"].get("on_route_name") == "Electronic City Flyover"]
    assert len(flyover) == 2 and flyover[0]["data"]["on_route"] == "flyover"
    # privacy: events carry distances and road names, never coordinates
    assert "lat" not in json.dumps(events) and "lon" not in json.dumps(events)


def test_websocket_reports_a_wrong_turn_with_the_contract_fields(client, trip):
    i = next(k for k in range(1, len(ROUTE)) if sum(haversine_m(ROUTE[j], ROUTE[j + 1]) for j in range(k)) > 2000)
    wrong = ROUTE[:i] + [destination(ROUTE[i - 1], (bearing_deg(ROUTE[i - 1], ROUTE[i]) + 90) % 360, 600)]
    rows = fixes(trip, path=wrong, seed=3)
    with client.websocket_connect(f"/v1/trips/{trip}/events", headers=AUTH) as ws:
        for k in range(0, len(rows), 60):
            post_gps(client, rows[k:k + 60])
        off = next(m for m in collect_until(ws, "off_route") if m["event"] == "off_route")
    assert off["data"]["recovery"]["action"] in {"u_turn", "turn_left", "turn_right", "continue", "reroute"}
    assert off["data"]["deviation_m"] > 20 and 0 < off["data"]["confidence"] <= 1
    ask = client.post("/v1/ask", json={"trip_id": trip, "intent": "am_i_wrong"}, headers=AUTH).json()
    assert ask["answer_key"] == "am_i_wrong.off_route"


def test_websocket_reconnect_replays_only_missed_events(client, trip):
    rows = fixes(trip)
    post_gps(client, rows[:200])                         # events happen with nobody listening
    post_gps(client, rows[200:400])
    with client.websocket_connect(f"/v1/trips/{trip}/events", headers=AUTH) as ws:
        first = ws.receive_json()
    assert first["seq"] == 1
    with client.websocket_connect(f"/v1/trips/{trip}/events?last_seq=3", headers=AUTH) as ws:
        assert ws.receive_json()["seq"] == 4


def test_websocket_rejects_missing_or_wrong_token_and_unknown_trips(client, trip):
    for headers, path in [({}, trip), ({"Authorization": "Bearer nope"}, trip), (AUTH, "trp_unknown")]:
        with pytest.raises(WebSocketDisconnect) as e:
            with client.websocket_connect(f"/v1/trips/{path}/events", headers=headers):
                pass
        assert e.value.code == 1008


def test_ending_a_trip_closes_its_websocket(client, trip):
    with client.websocket_connect(f"/v1/trips/{trip}/events", headers=AUTH) as ws:
        assert client.post(f"/v1/trips/{trip}/end", headers=AUTH).status_code == 204
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
    assert e.value.code == 1000
