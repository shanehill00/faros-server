"""Shared fixtures for faros_server tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

from faros_server.app import create_app
from faros_server.auth.jwt import create_token
from faros_server.config import Settings
from faros_server.db import close_db, create_tables, get_session, init_db
from faros_server.models.user import User, UserAuthMethod


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


async def create_test_user(
    name: str = "Test User",
    is_superuser: bool = True,
    provider: str = "google",
    provider_id: str = "google-123",
    email: str = "test@faros.dev",
) -> User:
    """Create a user with an auth method directly in the database."""
    async for session in get_session():
        user = User(
            name=name,
            is_superuser=is_superuser,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        auth_method = UserAuthMethod(
            user_id=user.id,
            provider=provider,
            provider_id=provider_id,
            email=email,
        )
        session.add(auth_method)
        await session.commit()
        await session.refresh(user)
        return user
    raise RuntimeError("No session available")


async def auth_headers(
    user: User | None = None,
    secret: str = "test-secret-key",
) -> dict[str, str]:
    """Generate JWT auth headers for a user."""
    if user is None:
        user = await create_test_user()
    token = create_token({"sub": user.id}, secret)
    return {"Authorization": f"Bearer {token}"}
