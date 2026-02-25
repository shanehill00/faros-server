"""Tests for OAuth provider implementations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from faros_server.auth.oauth import google_authorization_url, google_exchange_code


def test_google_authorization_url_contains_required_params() -> None:
    """Authorization URL includes client_id, redirect_uri, and scope."""
    url = google_authorization_url(
        client_id="cid-123",
        redirect_uri="http://localhost/callback",
        state="random-state",
    )
    assert "accounts.google.com" in url
    assert "cid-123" in url
    assert "random-state" in url
    assert "openid" in url


@pytest.mark.asyncio
async def test_google_exchange_code_success() -> None:
    """Successful code exchange returns OAuthUserInfo."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "gtoken-123"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {
        "id": "g-user-42",
        "email": "user@gmail.com",
        "name": "Test User",
        "picture": "https://example.com/photo.jpg",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("faros_server.auth.oauth.httpx.AsyncClient", return_value=mock_client):
        info = await google_exchange_code(
            code="auth-code",
            client_id="cid",
            client_secret="csecret",
            redirect_uri="http://localhost/callback",
        )

    assert info.provider == "google"
    assert info.provider_id == "g-user-42"
    assert info.email == "user@gmail.com"
    assert info.name == "Test User"
    assert info.avatar_url == "https://example.com/photo.jpg"


@pytest.mark.asyncio
async def test_google_exchange_code_token_failure() -> None:
    """Token exchange failure raises ValueError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "invalid_grant"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("faros_server.auth.oauth.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="token exchange failed"),
    ):
        await google_exchange_code("code", "cid", "csecret", "http://localhost/cb")


@pytest.mark.asyncio
async def test_google_exchange_code_no_access_token() -> None:
    """Missing access_token in response raises ValueError."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("faros_server.auth.oauth.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="No access_token"),
    ):
        await google_exchange_code("code", "cid", "csecret", "http://localhost/cb")


@pytest.mark.asyncio
async def test_google_exchange_code_userinfo_failure() -> None:
    """Userinfo request failure raises ValueError."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "tok"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 403
    mock_userinfo_resp.text = "forbidden"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("faros_server.auth.oauth.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="userinfo request failed"),
    ):
        await google_exchange_code("code", "cid", "csecret", "http://localhost/cb")


@pytest.mark.asyncio
async def test_google_exchange_code_missing_email() -> None:
    """Missing email in userinfo raises ValueError."""
    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {"access_token": "tok"}

    mock_userinfo_resp = MagicMock()
    mock_userinfo_resp.status_code = 200
    mock_userinfo_resp.json.return_value = {"id": "123"}  # no email

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_resp
    mock_client.get.return_value = mock_userinfo_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("faros_server.auth.oauth.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="did not return id or email"),
    ):
        await google_exchange_code("code", "cid", "csecret", "http://localhost/cb")
