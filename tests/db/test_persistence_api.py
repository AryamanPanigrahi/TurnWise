"""The API with a database attached: trips, wrong turns and arrivals end up in PostgreSQL."""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend import repository as repo
from backend.app import create_app
from backend.db import make_engine, make_session_factory
from backend.models import Deviation, Stop, Trip
from backend.persistence import TripPersistence
from backend.settings import Settings
from engine.geometry import bearing_deg, destination, haversine_m
from engine.synthetic import drive

BUNDLE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "routes"
                     / "mgroad-ecity.bundle.json").read_text(encoding="utf-8"))
ROUTE = [tuple(p) for p in BUNDLE["route"]]
TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BODY = {"origin": {"lat": 12.9757, "lon": 77.6061}, "destination": {"lat": 12.8456, "lon": 77.6603}}
FLEET = "Test Fleet"


def make_client(db_url):
    engine = make_engine(db_url)
    persistence = TripPersistence(make_session_factory(engine), FLEET)
    app = create_app(Settings(api_token=TOKEN), route_provider=lambda o, d: BUNDLE,
                     persistence=persistence, on_shutdown=engine.dispose)
    return TestClient(app)


def seed(run_db):
    """A fleet with a driver and a vehicle, plus a second fleet with a driver of its own."""
    async def scenario(sessions):
        async with sessions.begin() as s:
            mine = await repo.get_or_create_fleet(s, FLEET)
            other = await repo.get_or_create_fleet(s, "Someone Else")
            return {"driver": (await repo.add_driver(s, mine.id, "Asha")).id,
                    "vehicle": (await repo.add_vehicle(s, mine.id, "KA01AB1234", "truck")).id,
                    "stranger": (await repo.add_driver(s, other.id, "Zed")).id}
    return run_db(scenario)


def post_gps(client, rows):
    return client.post("/v1/gps", json={"points": rows}, headers=AUTH)


def wrong_turn_rows(trip_id):
    i = next(k for k in range(1, len(ROUTE)) if sum(haversine_m(ROUTE[j], ROUTE[j + 1]) for j in range(k)) > 2000)
    wrong = ROUTE[:i] + [destination(ROUTE[i - 1], (bearing_deg(ROUTE[i - 1], ROUTE[i]) + 90) % 360, 600)]
    return drive(wrong, trip_id=trip_id, speed_mps=15.0, noise_m=4.0, seed=3).rows


def test_trip_is_recorded_with_driver_vehicle_and_stops(db_url, run_db):
    ids = seed(run_db)
    with make_client(db_url) as client:
        r = client.post("/v1/trips", headers=AUTH, json={**BODY, "driver_id": str(ids["driver"]),
                                                          "vehicle_id": str(ids["vehicle"])})
        assert r.status_code == 201
        trip_id = r.json()["trip_id"]

    async def check(sessions):
        async with sessions() as s:
            t = await s.get(Trip, trip_id)
            n = await s.scalar(select(func.count()).select_from(Stop).where(Stop.trip_id == trip_id))
            return t.status, t.driver_id, t.vehicle_id, t.route_length_m, n

    status, driver, vehicle, length, stops = run_db(check)
    assert (status, driver, vehicle, stops) == ("active", ids["driver"], ids["vehicle"], 2)
    assert length == pytest.approx(BUNDLE["length_m"])


def test_wrong_turn_is_logged_and_closed_when_the_trip_ends(db_url, run_db):
    ids = seed(run_db)
    with make_client(db_url) as client:
        trip_id = client.post("/v1/trips", json={**BODY, "driver_id": str(ids["driver"])}, headers=AUTH).json()["trip_id"]
        rows = wrong_turn_rows(trip_id)
        for k in range(0, len(rows), 60):
            assert post_gps(client, rows[k:k + 60]).status_code == 202
        assert client.post(f"/v1/trips/{trip_id}/end", headers=AUTH).status_code == 204

    async def check(sessions):
        async with sessions() as s:
            trip = await s.get(Trip, trip_id)
            dev = (await s.scalars(select(Deviation).where(Deviation.trip_id == trip_id))).one()
            lat = await s.scalar(select(func.ST_Y(Deviation.location)).where(Deviation.id == dev.id))
            return trip.status, trip.ended_at, dev, lat

    status, trip_end, dev, lat = run_db(check)
    assert status == "ended" and trip_end is not None
    assert dev.reason == "distance" and dev.deviation_m > 20 and 0 < dev.confidence <= 1
    assert dev.ended_at.isoformat().startswith(rows[-1]["ts"][:19])   # closed at the LAST GPS FIX, not the server clock
    assert 20 < (dev.ended_at - dev.started_at).total_seconds() < 200
    assert 12.84 < lat < 12.98                         # a real location on the Bengaluru route


def test_returning_to_the_route_closes_the_episode(db_url, run_db):
    ids = seed(run_db)
    i = next(k for k in range(1, len(ROUTE)) if sum(haversine_m(ROUTE[j], ROUTE[j + 1]) for j in range(k)) > 2000)
    out = destination(ROUTE[i - 1], (bearing_deg(ROUTE[i - 1], ROUTE[i]) + 90) % 360, 300)
    path = ROUTE[:i] + [out, ROUTE[i - 1]] + ROUTE[i:i + 40]          # detour, U-turn, rejoin, carry on
    with make_client(db_url) as client:
        trip_id = client.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]
        rows = drive(path, trip_id=trip_id, speed_mps=15.0, noise_m=3.0, seed=4).rows
        for k in range(0, len(rows), 60):
            post_gps(client, rows[k:k + 60])
        # trip deliberately NOT ended: the episode must have been closed by back_on_route

    async def check(sessions):
        async with sessions() as s:
            return (await s.scalars(select(Deviation).where(Deviation.trip_id == trip_id))).all()

    devs = run_db(check)
    assert len(devs) == 1 and devs[0].ended_at is not None
    assert 20 < (devs[0].ended_at - devs[0].started_at).total_seconds() < 200


def test_arrival_is_recorded_on_the_destination_stop(db_url, run_db):
    seed(run_db)
    with make_client(db_url) as client:
        trip_id = client.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]
        rows = drive(ROUTE, trip_id=trip_id, speed_mps=15.0, noise_m=4.0, seed=11).rows
        for k in range(0, len(rows), 200):
            post_gps(client, rows[k:k + 200])

    async def check(sessions):
        async with sessions() as s:
            return [(x.seq, x.arrived_at is not None)
                    for x in (await s.scalars(select(Stop).where(Stop.trip_id == trip_id).order_by(Stop.seq))).all()]

    assert run_db(check) == [(0, False), (1, True)]


def test_a_driver_from_another_fleet_is_rejected_and_nothing_is_recorded(db_url, run_db):
    ids = seed(run_db)
    with make_client(db_url) as client:
        r = client.post("/v1/trips", json={**BODY, "driver_id": str(ids["stranger"])}, headers=AUTH)
        assert r.status_code == 422 and "driver" in r.json()["detail"]
        assert client.post("/v1/trips", json={**BODY, "vehicle_id": "00000000-0000-0000-0000-000000000000"},
                           headers=AUTH).status_code == 422

    async def count(sessions):
        async with sessions() as s:
            return await s.scalar(select(func.count()).select_from(Trip))

    assert run_db(count) == 0


def test_database_outage_blocks_new_trips_but_not_alerts(db_url, run_db, monkeypatch):
    seed(run_db)
    # 1. alerts keep flowing when recording an event fails
    with make_client(db_url) as client:
        trip_id = client.post("/v1/trips", json=BODY, headers=AUTH).json()["trip_id"]

        async def broken(*a, **k):
            raise ConnectionError("db went away")

        monkeypatch.setattr(repo, "open_deviation", broken)
        with client.websocket_connect(f"/v1/trips/{trip_id}/events", headers=AUTH) as ws:
            rows = wrong_turn_rows(trip_id)
            for k in range(0, len(rows), 60):
                assert post_gps(client, rows[k:k + 60]).status_code == 202
            seen = set()
            while "off_route" not in seen:
                seen.add(ws.receive_json()["event"])
        assert "off_route" in seen

    # 2. but with no database at all, a new trip is refused rather than silently untracked
    class Unreachable(TripPersistence):
        async def startup(self):                       # a real server would fail to boot here; pretend it booted earlier
            self.fleet_id = uuid.uuid4()

    dead = make_engine("postgresql+asyncpg://nobody:x@127.0.0.1:1/none")
    app = create_app(Settings(api_token=TOKEN), route_provider=lambda o, d: BUNDLE,
                     persistence=Unreachable(make_session_factory(dead), FLEET))
    with TestClient(app) as client:
        r = client.post("/v1/trips", json=BODY, headers=AUTH)
        assert r.status_code == 503
        assert client.post("/v1/gps", json={"points": drive(ROUTE, trip_id="x", seed=1).rows[:2]},
                           headers=AUTH).status_code == 403          # the half-created trip was discarded
