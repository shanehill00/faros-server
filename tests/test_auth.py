"""Tests for authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from litestar.testing import TestClient

from faros_server.clients.google_oauth_client import OAuthUserInfo
from faros_server.utils.jwt import JWTManager
from tests.conftest import auth_headers, create_test_user

_test_jwt = JWTManager(secret_key="test-secret-key", expire_minutes=30)


def _oauth_client(client: TestClient) -> object:  # type: ignore[type-arg]
    """Return the GoogleOAuthClient inside the AuthResource."""
    return client.app.state.auth._oauth_client


@pytest.mark.asyncio
async def test_login_google_redirects(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/auth/login/google redirects to Google OAuth."""
    _oauth_client(client)._client_id = "test-client-id"
    response =client.get("/api/auth/login/google", follow_redirects=False)
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert "test-client-id" in response.headers["location"]


def test_login_unsupported_provider(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/auth/login/github returns 400 (not yet supported)."""
    response =client.get("/api/auth/login/github")
    assert response.status_code == 400


def test_login_google_not_configured(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/auth/login/google returns 500 when client_id is empty."""
    response =client.get("/api/auth/login/google")
    assert response.status_code == 500


@pytest.mark.asyncio
async def test_callback_creates_user(client: TestClient) -> None:  # type: ignore[type-arg]
    """OAuth callback creates a new user with auth method and returns JWT."""
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-999",
        email="new@faros.dev",
        name="New User",
        avatar_url="https://example.com/avatar.jpg",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get("/api/auth/callback/google?code=test-code")
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_callback_first_user_is_superuser(client: TestClient) -> None:  # type: ignore[type-arg]
    """First user created via OAuth is automatically a superuser."""
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-first",
        email="first@faros.dev",
        name="First",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get("/api/auth/callback/google?code=test-code")
    token = response.json()["access_token"]
    me_response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    data = me_response.json()
    assert data["is_superuser"] is True
    assert data["auth_methods"] == [{"provider": "google", "email": "first@faros.dev"}]


@pytest.mark.asyncio
async def test_callback_second_user_not_superuser(client: TestClient) -> None:  # type: ignore[type-arg]
    """Second user created via OAuth is not a superuser."""
    await create_test_user()
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-second",
        email="second@faros.dev",
        name="Second",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get("/api/auth/callback/google?code=test-code")
    token = response.json()["access_token"]
    me_response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.json()["is_superuser"] is False


@pytest.mark.asyncio
async def test_callback_existing_user_updates_profile(client: TestClient) -> None:  # type: ignore[type-arg]
    """Existing user logging in again updates name and avatar."""
    await create_test_user(
        name="Old Name",
        provider="google",
        provider_id="g-returning",
        email="returning@faros.dev",
    )
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-returning",
        email="returning@faros.dev",
        name="New Name",
        avatar_url="https://example.com/new.jpg",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get("/api/auth/callback/google?code=test-code")
    token = response.json()["access_token"]
    me_response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_callback_exchange_failure(client: TestClient) -> None:  # type: ignore[type-arg]
    """OAuth callback returns 401 when code exchange fails."""
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        side_effect=ValueError("token exchange failed"),
    ):
        response =client.get("/api/auth/callback/google?code=bad-code")
    assert response.status_code == 401


def test_callback_unsupported_provider(client: TestClient) -> None:  # type: ignore[type-arg]
    """OAuth callback returns 400 for unsupported provider."""
    response =client.get("/api/auth/callback/github?code=test")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_callback_inactive_user(client: TestClient) -> None:  # type: ignore[type-arg]
    """OAuth callback returns 401 for inactive user."""
    from sqlalchemy import select

    from faros_server.models.user import User
    from faros_server.utils.db import Database

    await create_test_user(
        provider="google",
        provider_id="g-inactive",
        email="inactive@faros.dev",
    )
    async with Database.get_pool()() as session:
        result = await session.execute(
            select(User).where(User.name == "Test User")
        )
        user = result.scalar_one()
        user.is_active = False
        await session.commit()

    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-inactive",
        email="inactive@faros.dev",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get("/api/auth/callback/google?code=test-code")
    assert response.status_code == 401


# --- Link provider tests ---


@pytest.mark.asyncio
async def test_link_redirects_to_provider(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/auth/link/google redirects to Google OAuth (requires JWT)."""
    _oauth_client(client)._client_id = "test-client-id"
    user = await create_test_user()
    headers = await auth_headers(user)
    response =client.get(
        "/api/auth/link/google", headers=headers, follow_redirects=False
    )
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]
    assert "link" in response.headers["location"]


@pytest.mark.asyncio
async def test_link_callback_adds_auth_method(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link callback adds a new auth method to the existing user."""
    user = await create_test_user()
    headers = await auth_headers(user)
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-work-account",
        email="work@company.com",
        name="Test User",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get(
            "/api/auth/link/callback/google?code=link-code", headers=headers
        )
    assert response.status_code == 200
    data = response.json()
    assert len(data["auth_methods"]) == 2
    emails = {m["email"] for m in data["auth_methods"]}
    assert "test@faros.dev" in emails
    assert "work@company.com" in emails


@pytest.mark.asyncio
async def test_link_callback_duplicate_provider_409(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link callback returns 409 if provider account is already linked."""
    user = await create_test_user()
    headers = await auth_headers(user)
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="google-123",  # same as create_test_user default
        email="test@faros.dev",
    )
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        response =client.get(
            "/api/auth/link/callback/google?code=link-code", headers=headers
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_link_callback_exchange_failure(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link callback returns 401 when code exchange fails."""
    user = await create_test_user()
    headers = await auth_headers(user)
    with patch.object(
        _oauth_client(client), "exchange_code",
        new_callable=AsyncMock,
        side_effect=ValueError("token exchange failed"),
    ):
        response =client.get(
            "/api/auth/link/callback/google?code=bad-code", headers=headers
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_link_unsupported_provider(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link returns 400 for unsupported provider."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response =client.get("/api/auth/link/github", headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_link_callback_unsupported_provider(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link callback returns 400 for unsupported provider."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response =client.get(
        "/api/auth/link/callback/github?code=test", headers=headers
    )
    assert response.status_code == 400


def test_link_requires_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link endpoint requires JWT auth."""
    response =client.get("/api/auth/link/google")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_link_not_configured(client: TestClient) -> None:  # type: ignore[type-arg]
    """Link returns 500 when Google OAuth is not configured."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response =client.get("/api/auth/link/google", headers=headers)
    assert response.status_code == 500


# --- /me tests ---


@pytest.mark.asyncio
async def test_me_authenticated(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /me with valid token returns user with auth methods."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response =client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test User"
    assert len(data["auth_methods"]) == 1
    assert data["auth_methods"][0]["provider"] == "google"
    assert data["auth_methods"][0]["email"] == "test@faros.dev"


def test_me_no_token(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /me without token returns 401."""
    response =client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_bad_token(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /me with invalid token returns 401."""
    response =client.get(
        "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert response.status_code == 401


def test_me_bearer_prefix_required(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /me with token but no Bearer prefix returns 401."""
    response =client.get(
        "/api/auth/me", headers={"Authorization": "Token abc"}
    )
    assert response.status_code == 401


def test_me_token_no_sub_claim(client: TestClient) -> None:  # type: ignore[type-arg]
    """Token without 'sub' claim returns 401."""
    token = _test_jwt.create_token({"foo": "bar"})
    response =client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_token_user_deleted(client: TestClient) -> None:  # type: ignore[type-arg]
    """Token for nonexistent user returns 401."""
    await create_test_user()
    token = _test_jwt.create_token({"sub": "nonexistent-id-000"})
    response =client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_inactive_user(client: TestClient) -> None:  # type: ignore[type-arg]
    """Token for inactive user returns 401."""
    from sqlalchemy import select

    from faros_server.models.user import User
    from faros_server.utils.db import Database

    user = await create_test_user(email="inactive-me@faros.dev", provider_id="g-inact-me")
    async with Database.get_pool()() as session:
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()
        db_user.is_active = False
        await session.commit()

    headers = await auth_headers(user)
    response =client.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
