"""Tests for GoogleOAuthClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from faros_server.clients.google_oauth_client import GoogleOAuthClient

_HTTPX_CLIENT = "faros_server.clients.google_oauth_client.httpx.AsyncClient"


@pytest.fixture()
def oauth() -> GoogleOAuthClient:
    """A GoogleOAuthClient wired with test config."""
    return GoogleOAuthClient(
        client_id="cid-123",
        client_secret="csecret",
        base_url="http://localhost:8000",
    )


def test_is_configured(oauth: GoogleOAuthClient) -> None:
    """is_configured is True when client_id is set."""
    assert oauth.is_configured is True


def test_is_not_configured() -> None:
    """is_configured is False when client_id is empty."""
    empty = GoogleOAuthClient(client_id="", client_secret="", base_url="http://localhost")
    assert empty.is_configured is False


def test_provider(oauth: GoogleOAuthClient) -> None:
    """provider returns 'google'."""
    assert oauth.provider == "google"


def test_callback_uri(oauth: GoogleOAuthClient) -> None:
    """callback_uri builds the login callback URL."""
    assert oauth.callback_uri == "http://localhost:8000/api/auth/callback/google"


def test_link_callback_uri(oauth: GoogleOAuthClient) -> None:
    """link_callback_uri builds the link callback URL."""
    assert oauth.link_callback_uri == "http://localhost:8000/api/auth/link/callback/google"


def test_authorization_url(oauth: GoogleOAuthClient) -> None:
    """authorization_url includes client_id, redirect_uri, and scope."""
    url = oauth.authorization_url(
        redirect_uri="http://localhost/callback",
        state="random-state",
    )
    assert "accounts.google.com" in url
    assert "cid-123" in url
    assert "random-state" in url
    assert "openid" in url


@pytest.mark.asyncio
async def test_exchange_code_success(oauth: GoogleOAuthClient) -> None:
    """Successful code exchange returns OAuthUserInfo."""
    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"access_token": "gtoken-123"}

    mock_userinfo_response = MagicMock()
    mock_userinfo_response.status_code = 200
    mock_userinfo_response.json.return_value = {
        "id": "g-user-42",
        "email": "user@gmail.com",
        "name": "Test User",
        "picture": "https://example.com/photo.jpg",
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_response
    mock_client.get.return_value = mock_userinfo_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch(_HTTPX_CLIENT, return_value=mock_client):
        info = await oauth.exchange_code(
            code="auth-code",
            redirect_uri="http://localhost/callback",
        )

    assert info.provider == "google"
    assert info.provider_id == "g-user-42"
    assert info.email == "user@gmail.com"
    assert info.name == "Test User"
    assert info.avatar_url == "https://example.com/photo.jpg"


@pytest.mark.asyncio
async def test_exchange_code_token_failure(oauth: GoogleOAuthClient) -> None:
    """Token exchange failure raises ValueError."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "invalid_grant"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT, return_value=mock_client),
        pytest.raises(ValueError, match="token exchange failed"),
    ):
        await oauth.exchange_code("code", "http://localhost/cb")


@pytest.mark.asyncio
async def test_exchange_code_no_access_token(oauth: GoogleOAuthClient) -> None:
    """Missing access_token in response raises ValueError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT, return_value=mock_client),
        pytest.raises(ValueError, match="No access_token"),
    ):
        await oauth.exchange_code("code", "http://localhost/cb")


@pytest.mark.asyncio
async def test_exchange_code_userinfo_failure(oauth: GoogleOAuthClient) -> None:
    """Userinfo request failure raises ValueError."""
    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"access_token": "tok"}

    mock_userinfo_response = MagicMock()
    mock_userinfo_response.status_code = 403
    mock_userinfo_response.text = "forbidden"

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_response
    mock_client.get.return_value = mock_userinfo_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT, return_value=mock_client),
        pytest.raises(ValueError, match="userinfo request failed"),
    ):
        await oauth.exchange_code("code", "http://localhost/cb")


@pytest.mark.asyncio
async def test_exchange_code_missing_email(oauth: GoogleOAuthClient) -> None:
    """Missing email in userinfo raises ValueError."""
    mock_token_response = MagicMock()
    mock_token_response.status_code = 200
    mock_token_response.json.return_value = {"access_token": "tok"}

    mock_userinfo_response = MagicMock()
    mock_userinfo_response.status_code = 200
    mock_userinfo_response.json.return_value = {"id": "123"}  # no email

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_token_response
    mock_client.get.return_value = mock_userinfo_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(_HTTPX_CLIENT, return_value=mock_client),
        pytest.raises(ValueError, match="did not return id or email"),
    ):
        await oauth.exchange_code("code", "http://localhost/cb")
