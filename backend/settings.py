"""Settings, read from environment variables (see .env.example). No secrets in code."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    api_token: str | None            # shared bearer token (placeholder for per-driver JWT auth)
    valhalla_url: str = "http://localhost:8002"
    event_backlog: int = 500         # events kept per trip for reconnecting clients

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            api_token=os.environ.get("TURNWISE_API_TOKEN") or None,
            valhalla_url=os.environ.get("VALHALLA_URL", "http://localhost:8002"),
        )
