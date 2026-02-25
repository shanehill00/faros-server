"""FastAPI dependencies for authentication."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from faros_server.auth.jwt import decode_token
from faros_server.config import Settings
from faros_server.dao.user_dao import user_dao
from faros_server.db import get_session
from faros_server.models.user import User
from faros_server.services.user_service import UserService


def get_settings(request: Request) -> Settings:
    """Retrieve settings from app state."""
    settings: Settings = request.app.state.settings
    return settings


def get_user_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserService:
    """Build a request-scoped UserService."""
    return UserService(session)


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Extract and validate JWT bearer token, return the User.

    Raises:
        HTTPException: 401 if token is missing, invalid, or user not found.
    """
    settings: Settings = request.app.state.settings
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )
    token = auth[len("Bearer "):]
    try:
        payload = decode_token(token, settings.secret_key)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user = await user_dao.find_by_id(session, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return user
