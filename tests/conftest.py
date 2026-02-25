"""Shared fixtures for faros_server tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from litestar.testing import TestClient

from faros_server.app import create_app
from faros_server.config import Settings
from faros_server.models.user import User, UserAuthMethod
from faros_server.utils.db import Database
from faros_server.utils.jwt import JWTManager

_test_jwt = JWTManager(secret_key="test-secret-key", expire_minutes=30)


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
    with TestClient(app=app) as test_client:
        yield test_client


async def create_test_user(
    name: str = "Test User",
    is_superuser: bool = True,
    provider: str = "google",
    provider_id: str = "google-123",
    email: str = "test@faros.dev",
) -> User:
    """Create a user with an auth method directly in the database."""
    pool = Database.get_pool()
    async with pool() as session:
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


async def auth_headers(
    user: User | None = None,
) -> dict[str, str]:
    """Generate JWT auth headers for a user."""
    if user is None:
        user = await create_test_user()
    token = _test_jwt.create_token({"sub": user.id})
    return {"Authorization": f"Bearer {token}"}
