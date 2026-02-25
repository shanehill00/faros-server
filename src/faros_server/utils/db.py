"""Async database engine and connection pool."""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Database:
    """Manages the async engine and connection pool as class-level state.

    Call Database.init() once at startup, then use Database.get_pool()
    anywhere a session factory is needed.
    """

    _engine: ClassVar[AsyncEngine | None] = None
    _pool: ClassVar[async_sessionmaker[AsyncSession] | None] = None

    @staticmethod
    def init(database_url: str) -> async_sessionmaker[AsyncSession]:
        """Create the async engine and connection pool. Returns the pool."""
        kwargs: dict[str, Any] = {"echo": False}
        if database_url == "sqlite+aiosqlite://":
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        Database._engine = create_async_engine(database_url, **kwargs)
        Database._pool = async_sessionmaker(Database._engine, expire_on_commit=False)
        return Database._pool

    @staticmethod
    def get_pool() -> async_sessionmaker[AsyncSession]:
        """Return the connection pool. Call Database.init() first."""
        assert Database._pool is not None, "call Database.init() first"
        return Database._pool

    @staticmethod
    async def create_tables() -> None:
        """Create all tables from registered models."""
        import faros_server.models

        _ = faros_server.models  # Ensure model metadata is registered with Base
        assert Database._engine is not None, "call Database.init() first"
        async with Database._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @staticmethod
    async def close() -> None:
        """Dispose the async engine and release the connection pool."""
        if Database._engine is not None:
            await Database._engine.dispose()
            Database._engine = None
            Database._pool = None
