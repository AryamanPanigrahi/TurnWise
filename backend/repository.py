"""Database reads and writes, one function per thing the app needs.

All functions take an open `AsyncSession` and do NOT commit: the caller owns the
transaction, so several writes land together or not at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from geoalchemy2 import WKTElement
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Deviation, Driver, Fleet, Stop, Trip, Vehicle

SRID = 4326


def point(lat: float, lon: float) -> WKTElement:
    """A PostGIS point. NOTE the order: WKT is (longitude latitude)."""
    return WKTElement(f"POINT({lon} {lat})", srid=SRID)


def linestring(coords: Sequence[Sequence[float]]) -> WKTElement:
    """A PostGIS line from [(lat, lon), ...] pairs."""
    return WKTElement("LINESTRING(" + ", ".join(f"{lon} {lat}" for lat, lon in coords) + ")", srid=SRID)


def parse_ts(ts: str) -> datetime:
    """'2026-11-07T04:30:00.000Z' -> timezone-aware UTC datetime."""
    return datetime.fromisoformat(ts[:-1] + "+00:00").astimezone(timezone.utc)


# -- fleets, drivers, vehicles -----------------------------------------------------------------
async def get_or_create_fleet(session: AsyncSession, name: str) -> Fleet:
    fleet = await session.scalar(select(Fleet).where(Fleet.name == name))
    if fleet is None:
        fleet = Fleet(name=name)
        session.add(fleet)
        await session.flush()
    return fleet


async def add_driver(session: AsyncSession, fleet_id: uuid.UUID, name: str, phone: str | None = None,
                     consent_given_at: datetime | None = None) -> Driver:
    driver = Driver(fleet_id=fleet_id, name=name, phone=phone, consent_given_at=consent_given_at)
    session.add(driver)
    await session.flush()
    return driver


async def add_vehicle(session: AsyncSession, fleet_id: uuid.UUID, registration: str, kind: str = "other") -> Vehicle:
    vehicle = Vehicle(fleet_id=fleet_id, registration=registration, kind=kind)
    session.add(vehicle)
    await session.flush()
    return vehicle


async def driver_in_fleet(session: AsyncSession, fleet_id: uuid.UUID, driver_id: uuid.UUID) -> bool:
    return await session.scalar(
        select(func.count()).select_from(Driver).where(Driver.id == driver_id, Driver.fleet_id == fleet_id)) == 1


async def vehicle_in_fleet(session: AsyncSession, fleet_id: uuid.UUID, vehicle_id: uuid.UUID) -> bool:
    return await session.scalar(
        select(func.count()).select_from(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.fleet_id == fleet_id)) == 1


# -- trips ---------------------------------------------------------------------------------------
async def create_trip(session: AsyncSession, *, trip_id: str, fleet_id: uuid.UUID,
                      driver_id: uuid.UUID | None, vehicle_id: uuid.UUID | None,
                      route: Sequence[Sequence[float]], route_length_m: float,
                      started_at: datetime) -> Trip:
    """Insert the trip and its two stops (origin = 0, destination = 1) from the route's ends."""
    trip = Trip(id=trip_id, fleet_id=fleet_id, driver_id=driver_id, vehicle_id=vehicle_id,
                route=linestring(route), route_length_m=route_length_m, started_at=started_at)
    trip.stops = [Stop(seq=0, name="origin", location=point(*route[0])),
                  Stop(seq=1, name="destination", location=point(*route[-1]))]
    session.add(trip)
    await session.flush()
    return trip


async def end_trip(session: AsyncSession, trip_id: str, ended_at: datetime,
                   last_fix_at: datetime | None = None) -> None:
    """Mark the trip ended and close any wrong-way episode still open.

    `ended_at` is when the server was told (server clock). An open episode is closed at
    `last_fix_at`, the time of the last GPS fix, because deviations are timed by the
    device's clock; mixing the two clocks would give nonsense durations.
    """
    await session.execute(update(Trip).where(Trip.id == trip_id, Trip.status == "active")
                          .values(status="ended", ended_at=ended_at))
    await close_deviation(session, trip_id, last_fix_at or ended_at)


async def mark_arrived(session: AsyncSession, trip_id: str, arrived_at: datetime) -> None:
    """The last stop (the destination) was reached."""
    last = await session.scalar(select(func.max(Stop.seq)).where(Stop.trip_id == trip_id))
    if last is not None:
        await session.execute(update(Stop).where(Stop.trip_id == trip_id, Stop.seq == last,
                                                 Stop.arrived_at.is_(None)).values(arrived_at=arrived_at))


# -- deviations (the wrong-way log) -------------------------------------------------------------------
async def open_deviation(session: AsyncSession, *, trip_id: str, started_at: datetime, lat: float, lon: float,
                         deviation_m: float | None, reason: str | None, confidence: float | None) -> Deviation:
    dev = Deviation(trip_id=trip_id, started_at=started_at, location=point(lat, lon),
                    deviation_m=deviation_m, reason=reason, confidence=confidence)
    session.add(dev)
    await session.flush()
    return dev


async def close_deviation(session: AsyncSession, trip_id: str, ended_at: datetime) -> None:
    await session.execute(update(Deviation).where(Deviation.trip_id == trip_id, Deviation.ended_at.is_(None))
                          .values(ended_at=ended_at))


# -- reports --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DriverStats:
    driver_id: uuid.UUID
    name: str
    trips: int
    deviations: int
    minutes_lost: float     # total time spent off route, closed episodes only


async def driver_deviation_stats(session: AsyncSession, fleet_id: uuid.UUID, since: datetime) -> list[DriverStats]:
    """Per driver: trips since a date, wrong-way episodes, and minutes spent off route.

    Scoped to one fleet: another fleet's drivers can never appear.
    """
    trips = (select(Trip.driver_id, func.count(Trip.id.distinct()).label("trips"))
             .where(Trip.fleet_id == fleet_id, Trip.started_at >= since).group_by(Trip.driver_id).subquery())
    devs = (select(Trip.driver_id,
                   func.count(Deviation.id).label("deviations"),
                   func.coalesce(func.sum(func.extract("epoch", Deviation.ended_at - Deviation.started_at)), 0).label("secs"))
            .join(Deviation, Deviation.trip_id == Trip.id)
            .where(Trip.fleet_id == fleet_id, Trip.started_at >= since).group_by(Trip.driver_id).subquery())
    rows = await session.execute(
        select(Driver.id, Driver.name, trips.c.trips,
               func.coalesce(devs.c.deviations, 0), func.coalesce(devs.c.secs, 0))
        .join(trips, trips.c.driver_id == Driver.id)
        .outerjoin(devs, devs.c.driver_id == Driver.id)
        .where(Driver.fleet_id == fleet_id).order_by(Driver.name))
    return [DriverStats(i, n, t, d, round(float(s) / 60, 1)) for i, n, t, d, s in rows]
