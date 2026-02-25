"""Authentication endpoints: OAuth login, callback, me."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from faros_server.auth.deps import get_current_user, get_settings
from faros_server.auth.jwt import create_token
from faros_server.auth.oauth import OAuthUserInfo, google_authorization_url, google_exchange_code
from faros_server.config import Settings
from faros_server.db import get_session
from faros_server.models.user import User
from faros_server.schemas.user import Token, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])

_SUPPORTED_PROVIDERS = {"google"}


def _redirect_uri(settings: Settings, provider: str) -> str:
    """Build the OAuth callback URL for a provider."""
    return f"{settings.base_url}/api/auth/callback/{provider}"


def _validate_provider(provider: str) -> None:
    """Raise 400 if provider is not supported."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider: {provider}",
        )


@router.get("/login/{provider}")
async def login(
    provider: str,
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Redirect the user to the OAuth provider's consent screen."""
    _validate_provider(provider)
    if not settings.google_client_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured",
        )
    state = secrets.token_urlsafe(32)
    url = google_authorization_url(
        client_id=settings.google_client_id,
        redirect_uri=_redirect_uri(settings, provider),
        state=state,
    )
    return RedirectResponse(url=url, status_code=302)


async def _find_or_create_user(
    session: AsyncSession,
    info: OAuthUserInfo,
) -> User:
    """Find existing user by email or create a new one. First user = superuser."""
    result = await session.execute(select(User).where(User.email == info.email))
    user = result.scalar_one_or_none()
    if user is not None:
        # Update profile fields from provider on each login
        user.name = info.name
        user.avatar_url = info.avatar_url
        await session.commit()
        return user

    # First user = superuser
    count_result = await session.execute(select(func.count()).select_from(User))
    user_count = count_result.scalar_one()
    is_first = user_count == 0

    user = User(
        email=info.email,
        name=info.name,
        avatar_url=info.avatar_url,
        provider=info.provider,
        provider_id=info.provider_id,
        is_superuser=is_first,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.get("/callback/{provider}", response_model=Token)
async def callback(
    provider: str,
    code: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Handle OAuth callback: exchange code, find/create user, issue JWT."""
    _validate_provider(provider)
    try:
        info = await google_exchange_code(
            code=code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=_redirect_uri(settings, provider),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    user = await _find_or_create_user(session, info)
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


@router.get("/me", response_model=UserRead)
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Return the current authenticated user."""
    return user
