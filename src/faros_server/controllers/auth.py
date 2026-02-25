"""Authentication controller — thin HTTP adapter for AuthResource."""

from __future__ import annotations

from litestar import Controller, get
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
        self, provider: str, code: str, auth: AuthResource,
    ) -> dict[str, str]:
        """Handle OAuth callback: exchange code, find/create user, issue JWT."""
        try:
            return await auth.callback(provider, code)
        except UnsupportedProviderError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except AuthError as error:
            raise NotAuthorizedException(detail=str(error)) from error

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
