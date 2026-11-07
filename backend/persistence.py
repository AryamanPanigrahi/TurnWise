"""Glue between the live trip registry and the database.

The live path (GPS in -> alert out) must NEVER wait on, or fail because of, the
database: a wrong-way alert matters more than its log entry. So:

  * `trip_created` is the one write that can reject a request (503): we do not
    start tracking a trip we cannot record.
  * `on_event` and `trip_ended` run AFTER the event was already published to the
    app, and swallow database errors (logged), so a database outage cannot stop
    alerts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend import repository as repo

log = logging.getLogger("turnwise.persistence")


class UnknownReference(Exception):
    """The driver or vehicle given for a trip does not exist in this fleet."""


class TripPersistence:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], fleet_name: str = "Dev Fleet"):
        self._sessions = sessions
        self._fleet_name = fleet_name
        self.fleet_id: uuid.UUID | None = None

    async def startup(self) -> None:
        """Make sure the fleet this server writes to exists."""
        async with self._sessions.begin() as s:
            self.fleet_id = (await repo.get_or_create_fleet(s, self._fleet_name)).id

    # -- strict: failures propagate ----------------------------------------------------------------
    async def trip_created(self, *, trip_id: str, route: Sequence[Sequence[float]], route_length_m: float,
                           started_at: datetime, driver_id: uuid.UUID | None = None,
                           vehicle_id: uuid.UUID | None = None) -> None:
        assert self.fleet_id is not None, "call startup() first"
        async with self._sessions.begin() as s:
            if driver_id and not await repo.driver_in_fleet(s, self.fleet_id, driver_id):
                raise UnknownReference("driver")
            if vehicle_id and not await repo.vehicle_in_fleet(s, self.fleet_id, vehicle_id):
                raise UnknownReference("vehicle")
            await repo.create_trip(s, trip_id=trip_id, fleet_id=self.fleet_id, driver_id=driver_id,
                                   vehicle_id=vehicle_id, route=route, route_length_m=route_length_m,
                                   started_at=started_at)

    # -- best effort: failures are logged, never raised ------------------------------------------------
    async def on_event(self, trip_id: str, message: Mapping, fix: Mapping) -> None:
        try:
            ts = repo.parse_ts(message["ts"])
            async with self._sessions.begin() as s:
                kind, data = message["event"], message.get("data", {})
                if kind == "off_route":
                    await repo.open_deviation(
                        s, trip_id=trip_id, started_at=ts, lat=fix["lat"], lon=fix["lon"],
                        deviation_m=data.get("deviation_m"), reason=data.get("reason"),
                        confidence=data.get("confidence"))
                elif kind == "back_on_route":
                    await repo.close_deviation(s, trip_id, ts)
                elif kind == "arrived":
                    await repo.mark_arrived(s, trip_id, ts)
        except Exception:
            log.exception("could not record %s for trip %s", message.get("event"), trip_id)

    async def trip_ended(self, trip_id: str, ended_at: datetime, last_fix_at: datetime | None = None) -> None:
        try:
            async with self._sessions.begin() as s:
                await repo.end_trip(s, trip_id, ended_at, last_fix_at)
        except Exception:
            log.exception("could not record the end of trip %s", trip_id)
