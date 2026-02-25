"""Tests for database module edge cases."""

import os

import pytest

from faros_server.db import close_db, create_tables, get_pool, init_db
from faros_server.models.agent import Agent
from faros_server.models.user import User


@pytest.mark.asyncio
async def test_close_db_when_not_initialized() -> None:
    """close_db is a no-op when engine is None."""
    await close_db()


@pytest.mark.asyncio
async def test_get_pool_yields_connection() -> None:
    """Pool creates a working database connection."""
    init_db("sqlite+aiosqlite://")
    await create_tables()
    pool = get_pool()
    async with pool() as db:
        assert db is not None
    await close_db()


@pytest.mark.asyncio
async def test_init_db_file_based(tmp_path: object) -> None:
    """init_db with a file-based SQLite URL uses standard pooling."""
    db_path = os.path.join(str(tmp_path), "test.db")
    init_db(f"sqlite+aiosqlite:///{db_path}")
    await create_tables()
    pool = get_pool()
    async with pool() as db:
        assert db is not None
    await close_db()
    os.unlink(db_path)


@pytest.mark.asyncio
async def test_models_create_agent() -> None:
    """Agent and User models can be inserted and queried."""
    init_db("sqlite+aiosqlite://")
    await create_tables()
    pool = get_pool()
    async with pool() as db:
        user = User(
            name="Test User",
            is_superuser=False,
        )
        db.add(user)
        await db.flush()
        agent = Agent(
            name="test-agent",
            robot_type="test",
            owner_id=user.id,
        )
        db.add(agent)
        await db.commit()
        assert agent.id is not None
        assert agent.created_at is not None
    await close_db()
