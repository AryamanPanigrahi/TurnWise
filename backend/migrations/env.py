"""Alembic environment: how migrations connect to the database (async, via asyncpg)."""

import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from backend.models import Base

config = context.config
target_metadata = Base.metadata



def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("set DATABASE_URL (see .env.example)")
    return url


def include_object(obj, name, type_, reflected, compare_to):
    """Only ever touch tables WE define.

    The PostGIS image ships extra tables of its own in the same schema (spatial_ref_sys,
    a US "tiger" geocoder, topology). Without this filter, autogenerate would try to
    drop them. Anything in the database that is not in backend/models.py is ignored.
    """
    if type_ == "table":
        return name in target_metadata.tables
    table = getattr(obj, "table", None)          # indexes and constraints belong to a table
    return table is None or table.name in target_metadata.tables


def _configure(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata,
                      include_object=include_object, compare_type=True)


def _do_run(connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


asyncio.run(_run_online())
