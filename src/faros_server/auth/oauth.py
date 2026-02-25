"""OAuth provider implementations."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx


@dataclass
class OAuthUserInfo:
    """User info returned by an OAuth provider after authentication."""

    provider: str
    provider_id: str
    email: str
    name: str | None = None
    avatar_url: str | None = None


_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


def google_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
) -> str:
    """Build the Google OAuth2 authorization URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "offline",
        "prompt": "select_account",
    }
    return f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"


async def google_exchange_code(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> OAuthUserInfo:
    """Exchange a Google authorization code for user info.

    Args:
        code: Authorization code from Google callback.
        client_id: Google OAuth client ID.
        client_secret: Google OAuth client secret.
        redirect_uri: Must match the redirect_uri used in the authorization request.

    Returns:
        OAuthUserInfo with the user's Google profile.

    Raises:
        ValueError: If the token exchange or userinfo request fails.
    """
    async with httpx.AsyncClient() as client:
        # Exchange code for tokens
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            raise ValueError(f"Google token exchange failed: {token_resp.text}")
        tokens = token_resp.json()
        access_token = tokens.get("access_token")
        if not access_token:
            raise ValueError("No access_token in Google response")

        # Fetch user info
        userinfo_resp = await client.get(
            _GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_resp.status_code != 200:
            raise ValueError(f"Google userinfo request failed: {userinfo_resp.text}")
        info = userinfo_resp.json()

    provider_id = info.get("id", "")
    email = info.get("email", "")
    if not provider_id or not email:
        raise ValueError("Google did not return id or email")

    return OAuthUserInfo(
        provider="google",
        provider_id=str(provider_id),
        email=email,
        name=info.get("name"),
        avatar_url=info.get("picture"),
    )
