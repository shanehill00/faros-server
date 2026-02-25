"""Shared fixtures for faros_server tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from faros_server.app import create_app
from faros_server.config import Settings
from faros_server.db import close_db, create_tables, init_db


@pytest.fixture()
def settings() -> Settings:
    """Test settings with in-memory SQLite."""
    return Settings(
        secret_key="test-secret-key",
        database_url="sqlite+aiosqlite://",
        token_expire_minutes=30,
    )


@pytest.fixture()
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Async HTTP client wired to the test app with lifespan managed."""
    app = create_app(settings)

    @asynccontextmanager
    async def _lifespan() -> AsyncIterator[None]:
        init_db(settings.database_url)
        await create_tables()
        yield
        await close_db()

    async with _lifespan(), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
