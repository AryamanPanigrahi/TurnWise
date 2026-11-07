"""Request and response shapes. They mirror docs/contracts/ (gps.md, ask.md, events.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Intent = Literal["which_branch", "left_or_right", "distance_to_next", "am_i_wrong", "repeat", "eta", "unknown"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")   # contracts: consumers ignore unknown fields


class GpsPoint(_Base):
    trip_id: str
    ts: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    speed: float | None = Field(default=None, ge=0)                # m/s
    heading: float | None = Field(default=None, ge=0, lt=360)      # degrees, 0 = north
    accuracy: float | None = Field(default=None, ge=0)             # metres

    @field_validator("ts")
    @classmethod
    def _utc_iso(cls, v: str) -> str:
        if not v.endswith("Z"):
            raise ValueError("ts must be UTC ISO-8601 ending in Z")
        datetime.fromisoformat(v[:-1] + "+00:00")                   # raises ValueError if malformed
        return v


class GpsBatch(_Base):
    points: list[GpsPoint] = Field(min_length=1, max_length=600)   # 10 min at 1 Hz

    @model_validator(mode="after")
    def _one_trip(self):
        if len({p.trip_id for p in self.points}) != 1:
            raise ValueError("all points in a batch must belong to one trip")
        return self


class GpsAccepted(BaseModel):
    accepted: int
    duplicates: int
    late: int = 0       # accepted but older than a fix already processed: not fed to the engine


class AskRequest(_Base):
    trip_id: str
    intent: Intent
    slots: dict[str, Any] = Field(default_factory=dict)


class AskResponse(BaseModel):
    answer_key: str
    facts: dict[str, Any]


class Place(_Base):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class TripCreate(_Base):
    origin: Place
    destination: Place
    driver_id: uuid.UUID | None = None      # must belong to the server's fleet (when a database is configured)
    vehicle_id: uuid.UUID | None = None


class TripCreated(BaseModel):
    trip_id: str
    length_m: float
    decision_points: int
