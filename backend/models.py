"""Database tables (SQLAlchemy 2 declarative models). One class = one table.

Every row that belongs to a customer carries `fleet_id`: the fleet company is the
customer (CLAUDE.md), and later every query is filtered by it so one fleet can
never see another's drivers.

Geometry columns use PostGIS (SRID 4326 = plain GPS latitude/longitude) so the
dashboard can ask spatial questions ("deviations inside this area") in SQL.
Remember PostGIS point order is (longitude, latitude).

Times are stored as UTC `timestamptz`; the UI converts to IST.

DPDP: `Driver.consent_given_at` and `Deviation.location` are personal data. The
column for consent exists now; enforcing it and the retention job come with the
security work (CLAUDE.md rule 5).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

VEHICLE_KINDS = ("delivery", "truck", "ambulance", "school_bus", "other")
TRIP_STATUSES = ("active", "ended")


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Fleet(Base):
    __tablename__ = "fleets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = _now()


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    fleet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fleets.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(default=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))   # DPDP
    created_at: Mapped[datetime] = _now()


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("fleet_id", "registration", name="uq_vehicle_registration_per_fleet"),
        CheckConstraint(f"kind IN {VEHICLE_KINDS}", name="ck_vehicle_kind"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    fleet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fleets.id"), index=True)
    registration: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32), default="other")
    created_at: Mapped[datetime] = _now()


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint(f"status IN {TRIP_STATUSES}", name="ck_trip_status"),
        Index("ix_trips_fleet_started", "fleet_id", "started_at"),
        Index("ix_trips_route", "route", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)        # "trp_<hex>", same id the API hands out
    fleet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fleets.id"))
    driver_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("drivers.id"), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    route = mapped_column(Geometry("LINESTRING", srid=4326, spatial_index=False))   # the planned route
    route_length_m: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    stops: Mapped[list["Stop"]] = relationship(order_by="Stop.seq", cascade="all, delete-orphan")
    deviations: Mapped[list["Deviation"]] = relationship(order_by="Deviation.started_at",
                                                          cascade="all, delete-orphan")


class Stop(Base):
    __tablename__ = "stops"
    __table_args__ = (UniqueConstraint("trip_id", "seq", name="uq_stop_seq_per_trip"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)                            # 0 = origin, last = destination
    name: Mapped[str | None] = mapped_column(String(200))
    location = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Deviation(Base):
    """One wrong-way episode: opened by `off_route`, closed by `back_on_route` (or trip end)."""

    __tablename__ = "deviations"
    __table_args__ = (Index("ix_deviations_location", "location", postgresql_using="gist"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))   # where it was confirmed
    deviation_m: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(16))               # "distance" | "heading"
    confidence: Mapped[float | None] = mapped_column(Float)
