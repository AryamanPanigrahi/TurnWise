"""The field-test kit: phone page, sentence rendering, browser WebSocket auth, trace recorder."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import create_app
from backend.settings import Settings
from engine.geometry import bearing_deg, destination, haversine_m
from engine.synthetic import drive
from tools.trace_format import check_points, loads_jsonl

BUNDLE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "routes"
                     / "mgroad-ecity.bundle.json").read_text(encoding="utf-8"))
ROUTE = [tuple(p) for p in BUNDLE["route"]]
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"origin": {"lat": 12.9757, "lon": 77.6061}, "destination": {"lat": 12.8456, "lon": 77.6603}}


def client_with(**settings):
    app = create_app(Settings(api_token=TOKEN, **settings), route_provider=lambda o, d: BUNDLE)
    return TestClient(app)


@pytest.fixture()
def client():
    with client_with(field_kit=True) as c:
        yield c


@pytest.fixture()
def trip(client):
    return client.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]


def say(client, **body):
    r = client.post("/field/api/say", json=body, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()["text"]


# -- on/off and auth ---------------------------------------------------------------------------
def test_field_kit_is_off_by_default():
    with client_with() as c:
        assert c.get("/field").status_code == 404
        assert c.post("/field/api/say", json={}, headers=AUTH).status_code == 404


def test_page_is_served_and_holds_no_secret(client):
    r = client.get("/field")
    assert r.status_code == 200 and "TurnWise field test" in r.text
    assert TOKEN not in r.text
    assert "OpenStreetMap contributors" in r.text            # ODbL attribution (CLAUDE.md rule 6)


def test_field_api_needs_the_token(client, trip):
    assert client.get(f"/field/api/trips/{trip}/route").status_code == 401
    assert client.post("/field/api/say", json={"answer_key": "not_sure"}).status_code == 401


# -- route for the map ----------------------------------------------------------------------------
def test_route_endpoint_returns_polyline_and_decision_points(client, trip):
    r = client.get(f"/field/api/trips/{trip}/route", headers=AUTH).json()
    assert len(r["route"]) == len(ROUTE) and r["length_m"] == pytest.approx(BUNDLE["length_m"])
    flyover = [p for p in r["decision_points"] if p.get("on_route_name") == "Electronic City Flyover"]
    assert flyover and flyover[0]["type"] == "flyover_vs_service" and 8000 < flyover[0]["at_m"] < 8300
    assert client.get("/field/api/trips/trp_nope/route", headers=AUTH).status_code == 403


# -- sentences ---------------------------------------------------------------------------------------
def test_answers_are_phrased_by_the_voice_templates(client):
    text = say(client, lang="en", answer_key="which_branch.flyover",
               facts={"on_route": "flyover", "distance_m": 350, "landmark": None, "confidence": 0.9})
    assert "flyover" in text and "350" in text
    assert say(client, lang="en", answer_key="not_sure") == "I'm not sure, follow the screen."


def test_wrong_way_alert_is_always_spoken(client):
    data = {"reason": "distance", "deviation_m": 42, "confidence": 1.0, "recovery": {"action": "reroute"}}
    assert say(client, lang="en", event="off_route", data=data).startswith("Wrong way")
    assert say(client, lang="en", event="back_on_route") == "You are back on route."


def test_decision_point_announcements(client):
    flyover = {"type": "flyover_vs_service", "on_route": "flyover", "alternatives": ["surface_road"],
               "distance_m": 393, "landmark": None, "confidence": 0.9, "maneuver": "keep_right"}
    assert "flyover" in say(client, lang="en", event="decision_point_ahead", data=flyover)
    turn = {"type": "junction", "on_route": "turn_right", "alternatives": [], "distance_m": 91,
            "landmark": None, "confidence": 0.9, "maneuver": "turn_right"}
    assert "right" in say(client, lang="en", event="decision_point_ahead", data=turn)


def test_weak_or_unspeakable_facts_stay_silent_instead_of_guessing(client):
    weak = {"type": "fork", "on_route": "right_fork", "alternatives": [], "distance_m": 300,
            "landmark": None, "confidence": 0.5, "maneuver": "keep_right"}
    assert say(client, lang="en", event="decision_point_ahead", data=weak) is None
    roundabout = {"type": "roundabout", "on_route": "roundabout", "alternatives": [], "distance_m": 100,
                  "landmark": None, "confidence": 0.9, "maneuver": "roundabout"}
    assert say(client, lang="en", event="decision_point_ahead", data=roundabout) is None
    assert say(client, lang="en", event="arrived", data={"distance_m": 10}) is None
    # a fork where the route goes straight: "Go straight for 90 metres" would mislead, so say nothing
    straight = {"type": "fork", "on_route": "straight", "alternatives": ["surface_road"], "distance_m": 91,
                "landmark": None, "confidence": 0.8, "maneuver": "straight"}
    assert say(client, lang="en", event="decision_point_ahead", data=straight) is None


def test_am_i_wrong_while_off_route_gives_the_wrong_way_alert_not_a_shrug(client):
    text = say(client, lang="en", answer_key="am_i_wrong.off_route", facts={"recovery_action": "reroute"})
    assert text == "Wrong way! Follow the screen."
    full = say(client, lang="en", answer_key="am_i_wrong.off_route", facts={"recovery_action": "u_turn", "distance_m": 300})
    assert "U-turn" in full and "300" in full            # with full facts the real answer template is used


def test_hindi_and_kannada_are_available(client):
    facts = {"on_route": "flyover", "distance_m": 350, "landmark": None, "confidence": 0.9}
    texts = {lang: say(client, lang=lang, answer_key="which_branch.flyover", facts=facts) for lang in ("en", "hi", "kn")}
    assert all(texts.values()) and len(set(texts.values())) == 3
    assert client.get("/field/api/languages", headers=AUTH).json()["languages"] == ["en", "hi", "kn"]


def test_say_rejects_unknown_language_and_empty_request(client):
    assert client.post("/field/api/say", json={"lang": "xx", "answer_key": "eta"}, headers=AUTH).status_code == 422
    assert client.post("/field/api/say", json={"lang": "en"}, headers=AUTH).status_code == 422


# -- browser websocket auth ------------------------------------------------------------------------
def test_browser_can_authenticate_the_socket_with_a_subprotocol(client, trip):
    with client.websocket_connect(f"/v1/trips/{trip}/events", subprotocols=["turnwise", TOKEN]) as ws:
        assert ws.accepted_subprotocol == "turnwise"
        rows = drive(ROUTE, trip_id=trip, speed_mps=15.0, noise_m=3.0, seed=1).rows[:60]
        client.post("/v1/gps", json={"points": rows}, headers=AUTH)
        assert ws.receive_json()["event"] == "decision_point_ahead"


@pytest.mark.parametrize("protocols", [["turnwise", "wrong"], ["turnwise"], [TOKEN], ["other", TOKEN]])
def test_socket_rejects_bad_subprotocol_tokens(client, trip, protocols):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/v1/trips/{trip}/events", subprotocols=protocols):
            pass
    assert e.value.code == 1008


# -- trace recorder ------------------------------------------------------------------------------------
def test_recorder_writes_a_replayable_trace(tmp_path):
    i = next(k for k in range(1, len(ROUTE)) if sum(haversine_m(ROUTE[j], ROUTE[j + 1]) for j in range(k)) > 2000)
    wrong = ROUTE[:i] + [destination(ROUTE[i - 1], (bearing_deg(ROUTE[i - 1], ROUTE[i]) + 90) % 360, 600)]
    with client_with(record_dir=str(tmp_path)) as c:
        trip = c.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]
        rows = drive(wrong, trip_id=trip, speed_mps=15.0, noise_m=4.0, seed=3).rows
        c.post("/v1/gps", json={"points": rows[:100] + rows[90:]}, headers=AUTH)     # 10 duplicates in the batch

    fixes = loads_jsonl((tmp_path / f"{trip}.jsonl").read_text(encoding="utf-8"))
    assert len(fixes) == len(rows)                                # duplicates are not recorded twice
    assert check_points(fixes).errors == []                       # passes Ram's contract checker
    assert set(fixes[0]) == {"trip_id", "ts", "lat", "lon", "speed", "heading", "accuracy"}
    assert json.loads((tmp_path / f"{trip}.route.json").read_text(encoding="utf-8"))["route"] == BUNDLE["route"]
    events = loads_jsonl((tmp_path / f"{trip}.events.jsonl").read_text(encoding="utf-8"))
    assert "off_route" in [e["event"] for e in events]


def test_nothing_is_recorded_unless_asked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with client_with() as c:
        trip = c.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]
        c.post("/v1/gps", json={"points": drive(ROUTE, trip_id=trip, seed=1).rows[:30]}, headers=AUTH)
    assert list(tmp_path.rglob("*")) == []
