"""Data access for User and UserAuthMethod models."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from faros_server.models.user import User, UserAuthMethod


class UserDAO:
    """Stateless query methods for users and auth methods.

    Instantiated once and reused across requests. Session is passed per call.
    """

    async def find_by_id(self, session: AsyncSession, user_id: str) -> User | None:
        """Find a user by primary key."""
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def find_auth_method(
        self, session: AsyncSession, provider: str, provider_id: str
    ) -> UserAuthMethod | None:
        """Find an auth method by provider and provider_id."""
        result = await session.execute(
            select(UserAuthMethod).where(
                UserAuthMethod.provider == provider,
                UserAuthMethod.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_users(self, session: AsyncSession) -> int:
        """Return total number of users."""
        result = await session.execute(
            select(func.count()).select_from(User)
        )
        return int(result.scalar_one())

    async def create_user(
        self,
        session: AsyncSession,
        *,
        name: str | None,
        avatar_url: str | None,
        is_superuser: bool,
    ) -> User:
        """Insert a new user and flush to populate its id."""
        user = User(
            name=name,
            avatar_url=avatar_url,
            is_superuser=is_superuser,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        return user

    async def create_auth_method(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        provider: str,
        provider_id: str,
        email: str,
    ) -> UserAuthMethod:
        """Insert a new auth method."""
        auth_method = UserAuthMethod(
            user_id=user_id,
            provider=provider,
            provider_id=provider_id,
            email=email,
        )
        session.add(auth_method)
        return auth_method

    async def get_auth_methods(
        self, session: AsyncSession, user_id: str
    ) -> list[UserAuthMethod]:
        """Return all auth methods for a user."""
        result = await session.execute(
            select(UserAuthMethod).where(UserAuthMethod.user_id == user_id)
        )
        return list(result.scalars())


#: Module-level singleton — reused across all requests.
user_dao = UserDAO()
