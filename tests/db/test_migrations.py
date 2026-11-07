"""The schema in backend/models.py and the migrations must always agree."""

import asyncio

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.db.conftest import alembic_config

OURS = {"fleets", "drivers", "vehicles", "trips", "stops", "deviations"}


def query(url, sql):
    async def go():
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (await conn.execute(text(sql))).all()
        await engine.dispose()
        return rows
    return asyncio.run(go())


def test_migrations_create_every_table_and_postgis_works(db_url):
    tables = {r[0] for r in query(db_url, "select tablename from pg_tables where schemaname='public'")}
    assert OURS <= tables
    assert query(db_url, "select postgis_version()")[0][0].startswith("3.")


def test_models_and_migrations_match(db_url):
    # raises if backend/models.py has a change that no migration covers yet
    command.check(alembic_config(db_url))


def test_downgrade_then_upgrade_round_trips(db_url):
    cfg = alembic_config(db_url)
    command.downgrade(cfg, "base")
    left = {r[0] for r in query(db_url, "select tablename from pg_tables where schemaname='public'")}
    assert not (OURS & left)
    command.upgrade(cfg, "head")
    assert OURS <= {r[0] for r in query(db_url, "select tablename from pg_tables where schemaname='public'")}
