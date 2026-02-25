"""JWT token creation and verification with python-jose."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

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
