"""Authentication endpoints: OAuth login, callback, link, me."""

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
from faros_server.models.user import User, UserAuthMethod
from faros_server.schemas.user import AuthMethodRead, Token, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])

_SUPPORTED_PROVIDERS = {"google"}


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


async def _find_or_create_user(
    session: AsyncSession,
    info: OAuthUserInfo,
) -> User:
    """Find user by provider+provider_id, or create a new one. First user = superuser."""
    # Look up by auth method
    result = await session.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == info.provider,
            UserAuthMethod.provider_id == info.provider_id,
        )
    )
    auth_method = result.scalar_one_or_none()

    if auth_method is not None:
        # Existing auth method — load and update user
        user_result = await session.execute(
            select(User).where(User.id == auth_method.user_id)
        )
        user = user_result.scalar_one()
        user.name = info.name
        user.avatar_url = info.avatar_url
        auth_method.email = info.email
        await session.commit()
        return user

    # New user — first user = superuser
    count_result = await session.execute(select(func.count()).select_from(User))
    user_count = count_result.scalar_one()
    is_first = user_count == 0

    user = User(
        name=info.name,
        avatar_url=info.avatar_url,
        is_superuser=is_first,
        is_active=True,
    )
    session.add(user)
    await session.flush()

    auth_method = UserAuthMethod(
        user_id=user.id,
        provider=info.provider,
        provider_id=info.provider_id,
        email=info.email,
    )
    session.add(auth_method)
    await session.commit()
    await session.refresh(user)
    return user


async def _load_user_response(session: AsyncSession, user: User) -> dict[str, object]:
    """Load a user with their auth methods for the response."""
    methods_result = await session.execute(
        select(UserAuthMethod).where(UserAuthMethod.user_id == user.id)
    )
    methods = [
        AuthMethodRead(provider=m.provider, email=m.email)
        for m in methods_result.scalars()
    ]
    return {
        "id": user.id,
        "name": user.name,
        "avatar_url": user.avatar_url,
        "is_superuser": user.is_superuser,
        "is_active": user.is_active,
        "auth_methods": methods,
    }


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
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, str]:
    """Handle OAuth callback: exchange code, find/create user, issue JWT."""
    _validate_provider(provider)
    info = await _exchange_code(provider, code, settings, _redirect_uri(settings, provider))

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
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    """Handle OAuth link callback: add auth method to existing user."""
    _validate_provider(provider)
    info = await _exchange_code(
        provider, code, settings, _link_redirect_uri(settings, provider)
    )

    # Check if this provider_id is already linked to any user
    existing = await session.execute(
        select(UserAuthMethod).where(
            UserAuthMethod.provider == info.provider,
            UserAuthMethod.provider_id == info.provider_id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This provider account is already linked to a user",
        )

    auth_method = UserAuthMethod(
        user_id=user.id,
        provider=info.provider,
        provider_id=info.provider_id,
        email=info.email,
    )
    session.add(auth_method)
    await session.commit()

    return await _load_user_response(session, user)


@router.get("/me", response_model=UserRead)
async def me(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    """Return the current authenticated user with linked auth methods."""
    return await _load_user_response(session, user)
