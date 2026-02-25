"""Tests for authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from faros_server.auth.jwt import create_token
from faros_server.auth.oauth import OAuthUserInfo
from tests.conftest import auth_headers, create_test_user


@pytest.mark.asyncio
async def test_login_google_redirects(client: httpx.AsyncClient) -> None:
    """GET /api/auth/login/google redirects to Google OAuth."""
    # Patch settings to have a client_id
    client._transport.app.state.settings.google_client_id = "test-client-id"  # type: ignore[union-attr]
    resp = await client.get("/api/auth/login/google", follow_redirects=False)
    assert resp.status_code == 302
    assert "accounts.google.com" in resp.headers["location"]
    assert "test-client-id" in resp.headers["location"]


@pytest.mark.asyncio
async def test_login_unsupported_provider(client: httpx.AsyncClient) -> None:
    """GET /api/auth/login/github returns 400 (not yet supported)."""
    resp = await client.get("/api/auth/login/github")
    assert resp.status_code == 400
    assert "Unsupported provider" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_login_google_not_configured(client: httpx.AsyncClient) -> None:
    """GET /api/auth/login/google returns 500 when client_id is empty."""
    resp = await client.get("/api/auth/login/google")
    assert resp.status_code == 500
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_callback_creates_user(client: httpx.AsyncClient) -> None:
    """OAuth callback creates a new user and returns JWT."""
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-999",
        email="new@faros.dev",
        name="New User",
        avatar_url="https://example.com/avatar.jpg",
    )
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        resp = await client.get("/api/auth/callback/google?code=test-code")
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_callback_first_user_is_superuser(client: httpx.AsyncClient) -> None:
    """First user created via OAuth is automatically a superuser."""
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-first",
        email="first@faros.dev",
        name="First",
    )
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        resp = await client.get("/api/auth/callback/google?code=test-code")
    token = resp.json()["access_token"]
    me_resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.json()["is_superuser"] is True


@pytest.mark.asyncio
async def test_callback_second_user_not_superuser(client: httpx.AsyncClient) -> None:
    """Second user created via OAuth is not a superuser."""
    await create_test_user()
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-second",
        email="second@faros.dev",
        name="Second",
    )
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        resp = await client.get("/api/auth/callback/google?code=test-code")
    token = resp.json()["access_token"]
    me_resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.json()["is_superuser"] is False


@pytest.mark.asyncio
async def test_callback_existing_user_updates_profile(client: httpx.AsyncClient) -> None:
    """Existing user logging in again updates name and avatar."""
    await create_test_user(email="returning@faros.dev", name="Old Name")
    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-returning",
        email="returning@faros.dev",
        name="New Name",
        avatar_url="https://example.com/new.jpg",
    )
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        resp = await client.get("/api/auth/callback/google?code=test-code")
    token = resp.json()["access_token"]
    me_resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_resp.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_callback_exchange_failure(client: httpx.AsyncClient) -> None:
    """OAuth callback returns 401 when code exchange fails."""
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        side_effect=ValueError("token exchange failed"),
    ):
        resp = await client.get("/api/auth/callback/google?code=bad-code")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_callback_unsupported_provider(client: httpx.AsyncClient) -> None:
    """OAuth callback returns 400 for unsupported provider."""
    resp = await client.get("/api/auth/callback/github?code=test")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_callback_inactive_user(client: httpx.AsyncClient) -> None:
    """OAuth callback returns 401 for inactive user."""
    from sqlalchemy import select

    from faros_server.db import get_session
    from faros_server.models.user import User

    await create_test_user(email="inactive@faros.dev")
    async for session in get_session():
        result = await session.execute(
            select(User).where(User.email == "inactive@faros.dev")
        )
        user = result.scalar_one()
        user.is_active = False
        await session.commit()

    mock_info = OAuthUserInfo(
        provider="google",
        provider_id="g-inactive",
        email="inactive@faros.dev",
        name="Inactive",
    )
    with patch(
        "faros_server.routers.auth.google_exchange_code",
        new_callable=AsyncMock,
        return_value=mock_info,
    ):
        resp = await client.get("/api/auth/callback/google?code=test-code")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client: httpx.AsyncClient) -> None:
    """GET /me with valid token returns user info."""
    user = await create_test_user()
    headers = await auth_headers(user)
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "test@faros.dev"
    assert body["provider"] == "google"


@pytest.mark.asyncio
async def test_me_no_token(client: httpx.AsyncClient) -> None:
    """GET /me without token returns 401."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_bad_token(client: httpx.AsyncClient) -> None:
    """GET /me with invalid token returns 401."""
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_bearer_prefix_required(client: httpx.AsyncClient) -> None:
    """GET /me with token but no Bearer prefix returns 401."""
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": "Token abc"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_token_no_sub_claim(client: httpx.AsyncClient) -> None:
    """Token without 'sub' claim returns 401."""
    token = create_token({"foo": "bar"}, "test-secret-key")
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_token_user_deleted(client: httpx.AsyncClient) -> None:
    """Token for deleted user returns 401."""
    await create_test_user()
    # Use a fake user ID that doesn't exist in DB
    token = create_token({"sub": "nonexistent-id-000"}, "test-secret-key")
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_inactive_user(client: httpx.AsyncClient) -> None:
    """Token for inactive user returns 401."""
    from sqlalchemy import select

    from faros_server.db import get_session
    from faros_server.models.user import User

    user = await create_test_user(email="inactive-me@faros.dev")
    async for session in get_session():
        result = await session.execute(
            select(User).where(User.email == "inactive-me@faros.dev")
        )
        db_user = result.scalar_one()
        db_user.is_active = False
        await session.commit()

    headers = await auth_headers(user)
    resp = await client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 401
