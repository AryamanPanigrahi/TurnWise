"""Fixtures for tests that need the real PostgreSQL + PostGIS (`docker compose up -d db`).

Tests use a SEPARATE database whose name ends in `_test`; it is wiped of TurnWise tables at
the start of a run. If Postgres is not reachable the tests are skipped, unless
TURNWISE_REQUIRE_DB=1 (CI sets it) in which case they fail loudly.

Where the URL comes from, in order:
  1. TURNWISE_TEST_DATABASE_URL
  2. DATABASE_URL from the local .env, with the database name swapped to `turnwise_test`
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
TABLES = "deviations, stops, trips, vehicles, drivers, fleets"


def _test_url() -> str | None:
    url = os.environ.get("TURNWISE_TEST_DATABASE_URL")
    if not url and (ROOT / ".env").exists():
        m = re.search(r"^DATABASE_URL=(.+)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
        if m:
            url = re.sub(r"/[^/]+$", "/turnwise_test", m.group(1).strip())
    return url


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _reachable(url: str) -> str | None:
    try:
        conn = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"), timeout=3)
        await conn.close()
        return None
    except Exception as e:                          # connection refused, wrong password, no such database
        return f"{type(e).__name__}: {e}"


@pytest.fixture(scope="session")
def db_url():
    url = _test_url()
    problem = "no database URL (set TURNWISE_TEST_DATABASE_URL or create .env)" if not url else asyncio.run(_reachable(url))
    if problem:
        if os.environ.get("TURNWISE_REQUIRE_DB"):
            pytest.fail(f"database required but unavailable: {problem}")
        pytest.skip(f"PostgreSQL not available ({problem}); run `docker compose up -d db`")
    assert url.rsplit("/", 1)[-1].endswith("_test"), "refusing to wipe a database that is not named *_test"

    async def reset():
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TABLE IF EXISTS {TABLES}, alembic_version CASCADE"))
        await engine.dispose()

    asyncio.run(reset())
    command.upgrade(alembic_config(url), "head")
    return url


@pytest.fixture()
def run_db(db_url):
    """run_db(async_fn): run `async_fn(sessions)` against an empty database; returns its result."""

    async def truncate():
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        await engine.dispose()

    asyncio.run(truncate())

    def run(fn):
        async def go():
            engine = create_async_engine(db_url, poolclass=NullPool)
            try:
                return await fn(async_sessionmaker(engine, expire_on_commit=False))
            finally:
                await engine.dispose()
        return asyncio.run(go())

    return run
