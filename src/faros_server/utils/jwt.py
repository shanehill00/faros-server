"""JWT manager — constructed once at startup with signing config."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User


class JWTManager:
    """JWT token creation, verification, and user resolution.

    Built once at startup with the signing key, algorithm, and token lifetime.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expire_minutes: int = 60,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

    def create_token(self, claims: dict[str, Any]) -> str:
        """Create a signed JWT token.

        Args:
            claims: Claims to encode (must include ``sub``).

        Returns:
            Encoded JWT string.
        """
        to_encode = claims.copy()
        to_encode["exp"] = datetime.now(timezone.utc) + timedelta(
            minutes=self._expire_minutes,
        )
        return jwt.encode(to_encode, self._secret_key, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict[str, Any]:
        """Decode and verify a JWT token.

        Returns:
            Decoded claims dict.

        Raises:
            ValueError: If the token is invalid or expired.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token, self._secret_key, algorithms=[self._algorithm],
            )
        except JWTError as error:
            raise ValueError(f"Invalid token: {error}") from error
        return payload

    async def resolve_user(self, token: str, user_dao: UserDAO) -> User:
        """Decode a JWT token and return the corresponding active User.

        Raises:
            ValueError: If the token is invalid, has no sub claim,
                or the user is not found/inactive.
        """
        payload = self.decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("Invalid token payload: missing sub claim")
        async with user_dao.transaction():
            user = await user_dao.find_by_id(user_id)
        if user is None or not user.is_active:
            raise ValueError("User not found or inactive")
        return user
