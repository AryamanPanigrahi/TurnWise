"""Settings, read from environment variables (see .env.example). No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_token: str | None            # shared bearer token (placeholder for per-driver JWT auth)
    valhalla_url: str = "http://localhost:8002"
    event_backlog: int = 500         # events kept per trip for reconnecting clients
    database_url: str | None = None  # postgresql+asyncpg://...; without it trips are not recorded
    fleet_name: str = "Dev Fleet"    # which fleet this server records trips for (until auth maps tokens to fleets)
    field_kit: bool = False          # serve the phone-browser test client at /field (development only)
    record_dir: str | None = None    # write each trip's GPS to this folder for replay (development only)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_token=os.environ.get("TURNWISE_API_TOKEN") or None,
            valhalla_url=os.environ.get("VALHALLA_URL", "http://localhost:8002"),
            database_url=os.environ.get("DATABASE_URL") or None,
            fleet_name=os.environ.get("TURNWISE_FLEET_NAME", "Dev Fleet"),
            field_kit=os.environ.get("TURNWISE_FIELD_KIT", "") in ("1", "true", "yes"),
            record_dir=os.environ.get("TURNWISE_RECORD_DIR") or None,
        )
