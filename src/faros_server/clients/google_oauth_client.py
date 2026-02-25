"""OAuth provider client — constructed once at startup with all config."""

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


class GoogleOAuthClient:
    """Google OAuth2 client. Built once at startup, reused for every request."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str,
        auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth",
        token_url: str = "https://oauth2.googleapis.com/token",
        userinfo_url: str = "https://www.googleapis.com/oauth2/v2/userinfo",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url
        self._auth_url = auth_url
        self._token_url = token_url
        self._userinfo_url = userinfo_url

    @property
    def is_configured(self) -> bool:
        """True if client_id is set (minimum for OAuth to work)."""
        return bool(self._client_id)

    def callback_uri(self, provider: str) -> str:
        """Build the OAuth callback URL for login."""
        return f"{self._base_url}/api/auth/callback/{provider}"

    def link_callback_uri(self, provider: str) -> str:
        """Build the OAuth callback URL for account linking."""
        return f"{self._base_url}/api/auth/link/callback/{provider}"

    def authorization_url(self, redirect_uri: str, state: str) -> str:
        """Build the Google OAuth2 authorization URL."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{self._auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthUserInfo:
        """Exchange a Google authorization code for user info.

        Raises:
            ValueError: If the token exchange or userinfo request fails.
        """
        async with httpx.AsyncClient() as http_client:
            token_response = await http_client.post(
                self._token_url,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_response.status_code != 200:
                raise ValueError(
                    f"Google token exchange failed: {token_response.text}"
                )
            tokens = token_response.json()
            access_token = tokens.get("access_token")
            if not access_token:
                raise ValueError("No access_token in Google response")

            userinfo_response = await http_client.get(
                self._userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_response.status_code != 200:
                raise ValueError(
                    f"Google userinfo request failed: {userinfo_response.text}"
                )
            userinfo = userinfo_response.json()

        provider_id = userinfo.get("id", "")
        email = userinfo.get("email", "")
        if not provider_id or not email:
            raise ValueError("Google did not return id or email")

        return OAuthUserInfo(
            provider="google",
            provider_id=str(provider_id),
            email=email,
            name=userinfo.get("name"),
            avatar_url=userinfo.get("picture"),
        )
