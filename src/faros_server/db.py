"""Async database engine and connection pool."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


_engine = None
_pool: async_sessionmaker[AsyncSession] | None = None


def init_db(database_url: str) -> async_sessionmaker[AsyncSession]:
    """Create the async engine and connection pool. Returns the pool."""
    global _engine, _pool
    kwargs: dict[str, Any] = {"echo": False}
    if database_url == "sqlite+aiosqlite://":
        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_async_engine(database_url, **kwargs)
    _pool = async_sessionmaker(_engine, expire_on_commit=False)
    return _pool


def get_pool() -> async_sessionmaker[AsyncSession]:
    """Return the connection pool. Call init_db() first."""
    assert _pool is not None, "call init_db() first"
    return _pool


async def create_tables() -> None:
    """Create all tables from registered models."""
    import faros_server.models  # noqa: F401

    assert _engine is not None, "call init_db() first"
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the engine."""
    global _engine, _pool
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _pool = None
