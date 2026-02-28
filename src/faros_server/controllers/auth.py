"""Authentication controller — thin HTTP adapter for AuthResource."""

from __future__ import annotations

import base64
import json

from litestar import Controller, Request, get
from litestar.datastructures import State as LitestarState
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.response import Redirect

from faros_server.models.user import User
from faros_server.resources.auth import (
    AuthError,
    AuthResource,
    DuplicateLinkError,
    OAuthNotConfiguredError,
    UnsupportedProviderError,
)


class AuthController(Controller):
    """HTTP adapter for authentication and user account operations."""

    path = "/api/auth"

    @staticmethod
    def _extract_next_path(oauth_state: str) -> str | None:
        """Decode next_path from OAuth state. Returns None if absent or invalid."""
        if not oauth_state:
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(oauth_state).decode())
            path = str(data.get("next", ""))
        except (json.JSONDecodeError, ValueError, KeyError):
            return None
        # Prevent open redirect — only allow device approval paths
        if path.startswith("/api/agents/device/"):
            return path
        return None

    @get("/login/{provider:str}")
    async def login(self, provider: str, auth: AuthResource) -> Redirect:
        """Redirect the user to the OAuth provider's consent screen."""
        try:
            url = auth.login_url(provider)
            return Redirect(path=url, status_code=302)
        except UnsupportedProviderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OAuthNotConfiguredError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @get("/callback/{provider:str}")
    async def callback(
        self,
        provider: str,
        code: str,
        auth: AuthResource,
        request: Request[object, object, LitestarState],
    ) -> dict[str, str] | Redirect:
        """Handle OAuth callback. If state contains 'next', redirect with token."""
        try:
            result = await auth.callback(provider, code)
        except UnsupportedProviderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except AuthError as error:
            raise NotAuthorizedException(detail=str(error)) from error
        oauth_state = request.query_params.get("state", "")
        next_path = self._extract_next_path(oauth_state)
        if next_path is not None:
            token = result["access_token"]
            return Redirect(path=f"{next_path}?token={token}", status_code=302)
        return result

    @get("/link/{provider:str}")
    async def link_provider(
        self, provider: str, user: User, auth: AuthResource,
    ) -> Redirect:
        """Redirect logged-in user to OAuth provider to link a new auth method."""
        try:
            url = auth.link_url(provider)
            return Redirect(path=url, status_code=302)
        except UnsupportedProviderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OAuthNotConfiguredError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error

    @get("/link/callback/{provider:str}")
    async def link_callback(
        self, provider: str, code: str, user: User, auth: AuthResource,
    ) -> dict[str, object]:
        """Handle OAuth link callback: add auth method to existing user."""
        try:
            return await auth.link_callback(provider, code, user)
        except UnsupportedProviderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except AuthError as error:
            raise NotAuthorizedException(detail=str(error)) from error
        except DuplicateLinkError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @get("/me")
    async def me(self, user: User, auth: AuthResource) -> dict[str, object]:
        """Return the current authenticated user with linked auth methods."""
        return await auth.me(user)
