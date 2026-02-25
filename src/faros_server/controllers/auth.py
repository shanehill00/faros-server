"""Authentication controller: OAuth login, callback, link, me."""

from __future__ import annotations

import secrets

from litestar import Controller, get
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.response import Redirect

from faros_server.auth.jwt import create_token
from faros_server.auth.oauth import (
    OAuthUserInfo,
    google_authorization_url,
    google_exchange_code,
)
from faros_server.config import Settings
from faros_server.models.user import User
from faros_server.services.user_service import UserService

_SUPPORTED_PROVIDERS = {"google"}


def _validate_provider(provider: str) -> None:
    """Raise 400 if provider is not supported."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=400, detail=f"Unsupported provider: {provider}"
        )


def _validate_google_configured(settings: Settings) -> None:
    """Raise 500 if Google OAuth credentials are not set."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=500, detail="Google OAuth not configured"
        )


async def _exchange_code(
    provider: str, code: str, settings: Settings, redirect_uri: str
) -> OAuthUserInfo:
    """Exchange an OAuth authorization code for user info."""
    try:
        return await google_exchange_code(
            code=code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=redirect_uri,
        )
    except ValueError as exc:
        raise NotAuthorizedException(detail=str(exc)) from exc


def _redirect_uri(settings: Settings, provider: str) -> str:
    """Build the OAuth callback URL for a provider."""
    return f"{settings.base_url}/api/auth/callback/{provider}"


def _link_redirect_uri(settings: Settings, provider: str) -> str:
    """Build the OAuth link callback URL for a provider."""
    return f"{settings.base_url}/api/auth/link/callback/{provider}"


class AuthController(Controller):
    """HTTP endpoints for OAuth login, callback, account linking, and user info.

    All objects are pre-built at startup. svc is a singleton from app state.
    """

    path = "/api/auth"

    @get("/login/{provider:str}")
    async def login(self, provider: str, settings: Settings) -> Redirect:
        """Redirect the user to the OAuth provider's consent screen."""
        _validate_provider(provider)
        _validate_google_configured(settings)
        state = secrets.token_urlsafe(32)
        url = google_authorization_url(
            client_id=settings.google_client_id,
            redirect_uri=_redirect_uri(settings, provider),
            state=state,
        )
        return Redirect(path=url, status_code=302)

    @get("/callback/{provider:str}")
    async def callback(
        self, provider: str, code: str, svc: UserService, settings: Settings
    ) -> dict[str, str]:
        """Handle OAuth callback: exchange code, find/create user, issue JWT."""
        _validate_provider(provider)
        info = await _exchange_code(
            provider, code, settings, _redirect_uri(settings, provider)
        )
        user = await svc.find_or_create_user(info)
        if not user.is_active:
            raise NotAuthorizedException(detail="User account is inactive")
        token = create_token(
            {"sub": user.id},
            settings.secret_key,
            expire_minutes=settings.token_expire_minutes,
        )
        return {"access_token": token, "token_type": "bearer"}

    @get("/link/{provider:str}")
    async def link_provider(
        self, provider: str, user: User, settings: Settings
    ) -> Redirect:
        """Redirect logged-in user to OAuth provider to link a new auth method."""
        _validate_provider(provider)
        _validate_google_configured(settings)
        state = secrets.token_urlsafe(32)
        url = google_authorization_url(
            client_id=settings.google_client_id,
            redirect_uri=_link_redirect_uri(settings, provider),
            state=state,
        )
        return Redirect(path=url, status_code=302)

    @get("/link/callback/{provider:str}")
    async def link_callback(
        self, provider: str, code: str, user: User,
        svc: UserService, settings: Settings,
    ) -> dict[str, object]:
        """Handle OAuth link callback: add auth method to existing user."""
        _validate_provider(provider)
        info = await _exchange_code(
            provider, code, settings, _link_redirect_uri(settings, provider)
        )
        try:
            return await svc.link_auth_method(user, info)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="This provider account is already linked to a user",
            ) from exc

    @get("/me")
    async def me(self, user: User, svc: UserService) -> dict[str, object]:
        """Return the current authenticated user with linked auth methods."""
        return await svc.load_user_response(user)
