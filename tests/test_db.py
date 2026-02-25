"""Tests for database module edge cases."""

import pytest

from faros_server.db import close_db, create_tables, get_session, init_db


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
