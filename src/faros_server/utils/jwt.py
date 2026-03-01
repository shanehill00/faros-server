"""JWT manager — configured once at startup, all methods are class-level."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from jose import JWTError, jwt


class JWTManager:
    """JWT token creation and verification.

    Call ``configure()`` once at startup, then use class methods directly.
    """

    _secret_key: ClassVar[str] = ""
    _algorithm: ClassVar[str] = "HS256"
    _expire_minutes: ClassVar[int] = 60

    @classmethod
    def configure(
        cls,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expire_minutes: int = 60,
    ) -> None:
        """Set signing config. Call once at startup."""
        cls._secret_key = secret_key
        cls._algorithm = algorithm
        cls._expire_minutes = expire_minutes

    @classmethod
    def expire_seconds(cls) -> int:
        """Return the token expiration in seconds."""
        return cls._expire_minutes * 60

    @classmethod
    def create_token(cls, claims: dict[str, Any]) -> str:
        """Create a signed JWT token.

        Args:
            claims: Claims to encode (must include ``sub``).

        Returns:
            Encoded JWT string.
        """
        to_encode = claims.copy()
        to_encode["exp"] = datetime.now(timezone.utc) + timedelta(
            minutes=cls._expire_minutes,
        )
        return jwt.encode(to_encode, cls._secret_key, algorithm=cls._algorithm)

    @classmethod
    def decode_token(cls, token: str) -> dict[str, Any]:
        """Decode and verify a JWT token.

        Returns:
            Decoded claims dict.

        Raises:
            ValueError: If the token is invalid or expired.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token, cls._secret_key, algorithms=[cls._algorithm],
            )
        except JWTError as error:
            raise ValueError(f"Invalid token: {error}") from error
        return payload
