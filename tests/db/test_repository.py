"""Repository functions against the real PostgreSQL + PostGIS."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from backend import repository as repo
from backend.models import Deviation, Stop, Trip

T0 = datetime(2026, 11, 7, 4, 30, tzinfo=timezone.utc)
ROUTE = [(12.9757, 77.6061), (12.9700, 77.6200), (12.9500, 77.6400), (12.8456, 77.6603)]


async def make_trip(s, fleet, trip_id="trp_a", driver=None, vehicle=None, started=T0):
    return await repo.create_trip(s, trip_id=trip_id, fleet_id=fleet.id, driver_id=driver.id if driver else None,
                                  vehicle_id=vehicle.id if vehicle else None, route=ROUTE,
                                  route_length_m=17852.0, started_at=started)


def test_trip_is_stored_with_route_geometry_and_two_stops(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            fleet = await repo.get_or_create_fleet(s, "Acme Logistics")
            await make_trip(s, fleet)
        async with sessions() as s:
            trip = await s.get(Trip, "trp_a")
            npts = await s.scalar(select(func.ST_NPoints(Trip.route)).where(Trip.id == "trp_a"))
            stops = (await s.scalars(select(Stop).where(Stop.trip_id == "trp_a").order_by(Stop.seq))).all()
            # PostGIS order check: Y is latitude, X is longitude
            lat0 = await s.scalar(select(func.ST_Y(Stop.location)).where(Stop.trip_id == "trp_a", Stop.seq == 0))
            lon1 = await s.scalar(select(func.ST_X(Stop.location)).where(Stop.trip_id == "trp_a", Stop.seq == 1))
            return trip.status, trip.route_length_m, npts, [x.name for x in stops], lat0, lon1

    status, length, npts, names, lat0, lon1 = run_db(scenario)
    assert (status, length, npts, names) == ("active", 17852.0, 4, ["origin", "destination"])
    assert lat0 == pytest.approx(12.9757) and lon1 == pytest.approx(77.6603)


def test_get_or_create_fleet_is_idempotent(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            a = await repo.get_or_create_fleet(s, "Acme")
        async with sessions.begin() as s:
            b = await repo.get_or_create_fleet(s, "Acme")
        return a.id == b.id

    assert run_db(scenario) is True


def test_deviation_episode_opens_and_closes(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            fleet = await repo.get_or_create_fleet(s, "Acme")
            await make_trip(s, fleet)
            await repo.open_deviation(s, trip_id="trp_a", started_at=T0 + timedelta(minutes=5), lat=12.95, lon=77.62,
                                      deviation_m=45, reason="distance", confidence=0.95)
        async with sessions.begin() as s:
            await repo.close_deviation(s, "trp_a", T0 + timedelta(minutes=8))
        async with sessions() as s:
            d = (await s.scalars(select(Deviation))).one()
            return d.started_at, d.ended_at, d.reason, d.deviation_m

    started, ended, reason, dev_m = run_db(scenario)
    assert ended - started == timedelta(minutes=3)
    assert (reason, dev_m) == ("distance", 45)


def test_ending_a_trip_closes_an_open_deviation_and_is_idempotent(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            fleet = await repo.get_or_create_fleet(s, "Acme")
            await make_trip(s, fleet)
            await repo.open_deviation(s, trip_id="trp_a", started_at=T0, lat=12.9, lon=77.6,
                                      deviation_m=30, reason="heading", confidence=0.8)
        # server clock says 99 min; the last GPS fix was at 10 min. The episode must close at the fix time.
        for _ in range(2):                                                       # second call changes nothing
            async with sessions.begin() as s:
                await repo.end_trip(s, "trp_a", T0 + timedelta(minutes=99), last_fix_at=T0 + timedelta(minutes=10))
        async with sessions() as s:
            trip = await s.get(Trip, "trp_a")
            dev = (await s.scalars(select(Deviation))).one()
            return trip.status, trip.ended_at, dev.ended_at

    status, trip_end, dev_end = run_db(scenario)
    assert status == "ended" and trip_end == T0 + timedelta(minutes=99)
    assert dev_end == T0 + timedelta(minutes=10)


def test_arrival_marks_only_the_destination_stop(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            fleet = await repo.get_or_create_fleet(s, "Acme")
            await make_trip(s, fleet)
            await repo.mark_arrived(s, "trp_a", T0 + timedelta(minutes=30))
        async with sessions() as s:
            return [(x.seq, x.arrived_at) for x in
                    (await s.scalars(select(Stop).order_by(Stop.seq))).all()]

    assert run_db(scenario) == [(0, None), (1, T0 + timedelta(minutes=30))]


def test_vehicle_rules(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            a = await repo.get_or_create_fleet(s, "A")
            b = await repo.get_or_create_fleet(s, "B")
            await repo.add_vehicle(s, a.id, "KA01AB1234", "truck")
            await repo.add_vehicle(s, b.id, "KA01AB1234", "truck")           # same plate, other fleet: fine
        errors = []
        for fleet_name, reg, kind in [("A", "KA01AB1234", "truck"), ("A", "KA02", "spaceship")]:
            try:
                async with sessions.begin() as s:
                    fleet = await repo.get_or_create_fleet(s, fleet_name)
                    await repo.add_vehicle(s, fleet.id, reg, kind)
            except IntegrityError as e:
                errors.append("uq_vehicle_registration_per_fleet" if "uq_vehicle" in str(e) else "ck_vehicle_kind")
        return errors

    assert run_db(scenario) == ["uq_vehicle_registration_per_fleet", "ck_vehicle_kind"]


def test_driver_and_vehicle_membership_checks_are_per_fleet(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            a = await repo.get_or_create_fleet(s, "A")
            b = await repo.get_or_create_fleet(s, "B")
            d = await repo.add_driver(s, a.id, "Asha")
            v = await repo.add_vehicle(s, a.id, "KA01")
        async with sessions() as s:
            return (await repo.driver_in_fleet(s, a.id, d.id), await repo.driver_in_fleet(s, b.id, d.id),
                    await repo.vehicle_in_fleet(s, a.id, v.id), await repo.vehicle_in_fleet(s, b.id, v.id),
                    await repo.driver_in_fleet(s, a.id, uuid.uuid4()))

    assert run_db(scenario) == (True, False, True, False, False)


def test_driver_stats_count_minutes_lost_and_never_cross_fleets(run_db):
    async def scenario(sessions):
        async with sessions.begin() as s:
            a = await repo.get_or_create_fleet(s, "A")
            b = await repo.get_or_create_fleet(s, "B")
            asha = await repo.add_driver(s, a.id, "Asha")
            ravi = await repo.add_driver(s, a.id, "Ravi")
            other = await repo.add_driver(s, b.id, "Zed")                     # another customer
            await make_trip(s, a, "trp_1", asha)
            await make_trip(s, a, "trp_2", asha)
            await make_trip(s, a, "trp_3", ravi)
            await make_trip(s, b, "trp_4", other)
            await make_trip(s, a, "trp_old", ravi, started=T0 - timedelta(days=60))
            for trip, mins in [("trp_1", 1), ("trp_2", 2), ("trp_4", 50), ("trp_old", 9)]:
                await repo.open_deviation(s, trip_id=trip, started_at=T0, lat=12.9, lon=77.6,
                                          deviation_m=40, reason="distance", confidence=0.9)
                await repo.close_deviation(s, trip, T0 + timedelta(minutes=mins))
        async with sessions() as s:
            return await repo.driver_deviation_stats(s, a.id, since=T0 - timedelta(days=30))

    stats = {x.name: x for x in run_db(scenario)}
    assert set(stats) == {"Asha", "Ravi"}                                      # Zed (fleet B) never appears
    assert (stats["Asha"].trips, stats["Asha"].deviations, stats["Asha"].minutes_lost) == (2, 2, 3.0)
    assert (stats["Ravi"].trips, stats["Ravi"].deviations, stats["Ravi"].minutes_lost) == (1, 0, 0.0)  # old trip excluded


def test_postgis_can_find_deviations_near_a_point(run_db):
    """The dashboard heatmap relies on this: spatial search in SQL."""
    async def scenario(sessions):
        async with sessions.begin() as s:
            fleet = await repo.get_or_create_fleet(s, "A")
            await make_trip(s, fleet)
            for lat, lon in [(12.9500, 77.6200), (12.9505, 77.6203), (13.0500, 77.7000)]:   # 2 close, 1 far
                await repo.open_deviation(s, trip_id="trp_a", started_at=T0, lat=lat, lon=lon,
                                          deviation_m=40, reason="distance", confidence=0.9)
        async with sessions() as s:
            return await s.scalar(text(
                "select count(*) from deviations where ST_DWithin("
                "location::geography, ST_SetSRID(ST_MakePoint(77.6201, 12.9502), 4326)::geography, 500)"))

    assert run_db(scenario) == 2
