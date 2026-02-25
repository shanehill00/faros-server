"""Authentication helpers for extracting the current user from a request."""

from __future__ import annotations

from litestar import Request
from litestar.datastructures import State
from litestar.exceptions import NotAuthorizedException

from faros_server.auth.jwt import decode_token
from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User


async def current_user_from_token(
    token: str, secret_key: str, dao: UserDAO
) -> User:
    """Validate a JWT token and return the User.

    Raises:
        NotAuthorizedException: If the token is invalid or user not found/inactive.
    """
    try:
        payload = decode_token(token, secret_key)
    except ValueError as exc:
        raise NotAuthorizedException(detail="Invalid or expired token") from exc
    user_id = payload.get("sub")
    if user_id is None:
        raise NotAuthorizedException(detail="Invalid token payload")
    async with dao.transaction():
        user = await dao.find_by_id(user_id)
    if user is None or not user.is_active:
        raise NotAuthorizedException(detail="User not found or inactive")
    return user


async def provide_current_user(
    request: Request[object, object, State],
) -> User:
    """Litestar dependency — extract authenticated user from Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise NotAuthorizedException(
            detail="Missing or invalid Authorization header"
        )
    token = auth[len("Bearer "):]
    settings = request.app.state.settings
    dao: UserDAO = request.app.state.dao
    return await current_user_from_token(token, settings.secret_key, dao)
