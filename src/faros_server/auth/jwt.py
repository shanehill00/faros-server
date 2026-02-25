"""JWT token creation, verification, and user resolution."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User

_ALGORITHM = "HS256"


def create_token(
    data: dict[str, Any],
    secret: str,
    expire_minutes: int = 60,
) -> str:
    """Create a signed JWT token.

    Args:
        data: Claims to encode (must include ``sub``).
        secret: HMAC signing key.
        expire_minutes: Token lifetime in minutes.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    to_encode["exp"] = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    return jwt.encode(to_encode, secret, algorithm=_ALGORITHM)


def decode_token(token: str, secret: str) -> dict[str, Any]:
    """Decode and verify a JWT token.

    Args:
        token: Encoded JWT string.
        secret: HMAC signing key.

    Returns:
        Decoded claims dict.

    Raises:
        ValueError: If the token is invalid or expired.
    """
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[_ALGORITHM])
    except JWTError as exc:
        raise ValueError(f"Invalid token: {exc}") from exc
    return payload


async def current_user_from_token(
    token: str, secret_key: str, dao: UserDAO
) -> User:
    """Decode a JWT token and return the corresponding active User.

    Raises:
        ValueError: If the token is invalid, has no sub claim,
            or the user is not found/inactive.
    """
    payload = decode_token(token, secret_key)
    user_id = payload.get("sub")
    if user_id is None:
        raise ValueError("Invalid token payload: missing sub claim")
    async with dao.transaction():
        user = await dao.find_by_id(user_id)
    if user is None or not user.is_active:
        raise ValueError("User not found or inactive")
    return user
