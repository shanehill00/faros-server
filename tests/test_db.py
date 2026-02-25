"""Tests for database module edge cases."""

import pytest

from faros_server.db import close_db, create_tables, get_session, init_db
from faros_server.models.agent import Agent
from faros_server.models.user import User


@pytest.mark.asyncio
async def test_close_db_when_not_initialized() -> None:
    """close_db is a no-op when engine is None."""
    await close_db()


@pytest.mark.asyncio
async def test_get_session_yields_session() -> None:
    """get_session yields a working async session."""
    init_db("sqlite+aiosqlite://")
    await create_tables()
    async for session in get_session():
        assert session is not None
    await close_db()


@pytest.mark.asyncio
async def test_models_create_agent() -> None:
    """Agent and User models can be inserted and queried."""
    init_db("sqlite+aiosqlite://")
    await create_tables()
    async for session in get_session():
        user = User(
            email="test@example.com",
            hashed_password="fakehash",
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
    await close_db()
