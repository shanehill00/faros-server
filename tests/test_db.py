"""Tests for Database class edge cases."""

import os

import pytest

from faros_server.models.agent import Agent
from faros_server.models.user import User
from faros_server.utils.db import Database


@pytest.mark.asyncio
async def test_close_when_not_initialized() -> None:
    """Database.close() is a no-op when engine is None."""
    await Database.close()


@pytest.mark.asyncio
async def test_get_pool_yields_connection() -> None:
    """Pool creates a working database connection."""
    Database.init("sqlite+aiosqlite://")
    await Database.create_tables()
    pool = Database.get_pool()
    async with pool() as session:
        assert session is not None
    await Database.close()


@pytest.mark.asyncio
async def test_init_file_based(tmp_path: object) -> None:
    """Database.init() with a file-based SQLite URL uses standard pooling."""
    db_path = os.path.join(str(tmp_path), "test.db")
    Database.init(f"sqlite+aiosqlite:///{db_path}")
    await Database.create_tables()
    pool = Database.get_pool()
    async with pool() as session:
        assert session is not None
    await Database.close()
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_models_create_agent() -> None:
    """Agent and User models can be inserted and queried."""
    Database.init("sqlite+aiosqlite://")
    await Database.create_tables()
    pool = Database.get_pool()
    async with pool() as session:
        user = User(
            name="Test User",
            is_superuser=False,
        )
        session.add(user)
        await session.flush()
        agent = Agent(
            name="test-agent",
            robot_type="test",
            owner_id=user.id,
        )
        session.add(agent)
        await session.commit()
        assert agent.id is not None
        assert agent.created_at is not None
    await Database.close()
