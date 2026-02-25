"""Data access for User and UserAuthMethod models."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from faros_server.models.user import User, UserAuthMethod

# Module-private: tracks the active connection for the current unit of work.
_active_conn: ContextVar[AsyncSession] = ContextVar("_dao_conn")


class UserDAO:
    """Data access built once at startup with the connection pool.

    Use transaction() to wrap a group of operations in one unit of work.
    """

    def __init__(self, pool: async_sessionmaker[AsyncSession]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Open a unit of work. All DAO calls inside share one connection."""
        async with self._pool() as connection:
            context_token = _active_conn.set(connection)
            try:
                yield
            finally:
                _active_conn.reset(context_token)

    def _conn(self) -> AsyncSession:
        """Return the current unit-of-work connection."""
        return _active_conn.get()

    async def find_by_id(self, user_id: str) -> User | None:
        """Find a user by primary key."""
        result = await self._conn().execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def find_auth_method(
        self, provider: str, provider_id: str
    ) -> UserAuthMethod | None:
        """Find an auth method by provider and provider_id."""
        result = await self._conn().execute(
            select(UserAuthMethod).where(
                UserAuthMethod.provider == provider,
                UserAuthMethod.provider_id == provider_id,
            )
        )
        return result.scalar_one_or_none()

    async def count_users(self) -> int:
        """Return total number of users."""
        result = await self._conn().execute(
            select(func.count()).select_from(User)
        )
        return int(result.scalar_one())

    async def create_user(
        self,
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
        self._conn().add(user)
        await self._conn().flush()
        return user

    async def create_auth_method(
        self,
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
        self._conn().add(auth_method)
        return auth_method

    async def get_auth_methods(self, user_id: str) -> list[UserAuthMethod]:
        """Return all auth methods for a user."""
        result = await self._conn().execute(
            select(UserAuthMethod).where(UserAuthMethod.user_id == user_id)
        )
        return list(result.scalars())

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn().commit()

    async def refresh(self, instance: User) -> None:
        """Refresh an instance from the database."""
        await self._conn().refresh(instance)
