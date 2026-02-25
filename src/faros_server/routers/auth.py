"""Authentication endpoints: OAuth login, callback, link, me."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from faros_server.auth.deps import get_current_user, get_settings
from faros_server.auth.jwt import create_token
from faros_server.auth.oauth import OAuthUserInfo, google_authorization_url, google_exchange_code
from faros_server.config import Settings
from faros_server.dao.user_dao import UserDAO
from faros_server.db import get_session
from faros_server.models.user import User
from faros_server.schemas.user import Token, UserRead
from faros_server.services.user_service import UserService

router = APIRouter(prefix="/api/auth", tags=["auth"])

_SUPPORTED_PROVIDERS = {"google"}


def _get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    """Build a UserService wired to the request's DB session."""
    return UserService(UserDAO(session))


def _redirect_uri(settings: Settings, provider: str) -> str:
    """Build the OAuth callback URL for a provider."""
    return f"{settings.base_url}/api/auth/callback/{provider}"


def _link_redirect_uri(settings: Settings, provider: str) -> str:
    """Build the OAuth link callback URL for a provider."""
    return f"{settings.base_url}/api/auth/link/callback/{provider}"


def _validate_provider(provider: str) -> None:
    """Raise 400 if provider is not supported."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider: {provider}",
        )


def _validate_google_configured(settings: Settings) -> None:
    """Raise 500 if Google OAuth credentials are not set."""
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured",
        )


async def _exchange_code(
    provider: str,
    code: str,
    settings: Settings,
    redirect_uri: str,
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc


@router.get("/login/{provider}")
async def login(
    provider: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Redirect the user to the OAuth provider's consent screen."""
    _validate_provider(provider)
    _validate_google_configured(settings)
    state = secrets.token_urlsafe(32)
    url = google_authorization_url(
        client_id=settings.google_client_id,
        redirect_uri=_redirect_uri(settings, provider),
        state=state,
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/callback/{provider}", response_model=Token)
async def callback(
    provider: str,
    code: str,
    svc: Annotated[UserService, Depends(_get_user_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Handle OAuth callback: exchange code, find/create user, issue JWT."""
    _validate_provider(provider)
    info = await _exchange_code(
        provider, code, settings, _redirect_uri(settings, provider)
    )

    user = await svc.find_or_create_user(info)
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive",
        )
    token = create_token(
        {"sub": user.id},
        settings.secret_key,
        expire_minutes=settings.token_expire_minutes,
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/link/{provider}")
async def link_provider(
    provider: str,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Redirect logged-in user to OAuth provider to link a new auth method."""
    _validate_provider(provider)
    _validate_google_configured(settings)
    state = secrets.token_urlsafe(32)
    url = google_authorization_url(
        client_id=settings.google_client_id,
        redirect_uri=_link_redirect_uri(settings, provider),
        state=state,
    )
    return RedirectResponse(url=url, status_code=302)


@router.get("/link/callback/{provider}", response_model=UserRead)
async def link_callback(
    provider: str,
    code: str,
    user: Annotated[User, Depends(get_current_user)],
    svc: Annotated[UserService, Depends(_get_user_service)],
    settings: Annotated[Settings, Depends(get_settings)],
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
            status_code=status.HTTP_409_CONFLICT,
            detail="This provider account is already linked to a user",
        ) from exc


@router.get("/me", response_model=UserRead)
async def me(
    user: Annotated[User, Depends(get_current_user)],
    svc: Annotated[UserService, Depends(_get_user_service)],
) -> dict[str, object]:
    """Return the current authenticated user with linked auth methods."""
    return await svc.load_user_response(user)
