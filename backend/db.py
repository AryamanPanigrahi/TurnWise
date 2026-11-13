"""Database plumbing: engine and session factory (SQLAlchemy 2, async, asyncpg)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    # pool_pre_ping: a connection that went stale (DB restart) is replaced instead of failing a request
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
