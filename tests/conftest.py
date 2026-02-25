"""Shared fixtures for faros_server tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from litestar.testing import TestClient

from faros_server.app import create_app
from faros_server.auth.jwt import create_token
from faros_server.config import Settings
from faros_server.db import get_pool
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
def client(settings: Settings) -> Iterator[TestClient]:  # type: ignore[type-arg]
    """Sync test client wired to the test app."""
    app = create_app(settings)
    with TestClient(app=app) as tc:
        yield tc


async def create_test_user(
    name: str = "Test User",
    is_superuser: bool = True,
    provider: str = "google",
    provider_id: str = "google-123",
    email: str = "test@faros.dev",
) -> User:
    """Create a user with an auth method directly in the database."""
    pool = get_pool()
    async with pool() as db:
        user = User(
            name=name,
            is_superuser=is_superuser,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        auth_method = UserAuthMethod(
            user_id=user.id,
            provider=provider,
            provider_id=provider_id,
            email=email,
        )
        db.add(auth_method)
        await db.commit()
        await db.refresh(user)
        return user


async def auth_headers(
    user: User | None = None,
    secret: str = "test-secret-key",
) -> dict[str, str]:
    """Generate JWT auth headers for a user."""
    if user is None:
        user = await create_test_user()
    token = create_token({"sub": user.id}, secret)
    return {"Authorization": f"Bearer {token}"}
