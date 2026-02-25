"""Business logic for user accounts and auth method linking."""

from __future__ import annotations

from faros_server.auth.oauth import OAuthUserInfo
from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User


class UserService:
    """User business logic — delegates all data access to DAO."""

    def __init__(self, dao: UserDAO) -> None:
        self._dao = dao

    async def find_or_create_user(self, info: OAuthUserInfo) -> User:
        """Find user by provider+provider_id, or create a new one.

        Returning users get their name and avatar updated.
        First user in the system is automatically a superuser.
        """
        auth_method = await self._dao.find_auth_method(
            info.provider, info.provider_id
        )

        if auth_method is not None:
            user = await self._dao.find_by_id(auth_method.user_id)
            if user is None:  # pragma: no cover — defensive
                msg = f"User {auth_method.user_id} not found for auth method"
                raise ValueError(msg)
            user.name = info.name
            user.avatar_url = info.avatar_url
            auth_method.email = info.email
            await self._dao.commit()
            return user

        user_count = await self._dao.count_users()
        is_first = user_count == 0

        user = await self._dao.create_user(
            name=info.name,
            avatar_url=info.avatar_url,
            is_superuser=is_first,
        )
        await self._dao.create_auth_method(
            user_id=user.id,
            provider=info.provider,
            provider_id=info.provider_id,
            email=info.email,
        )
        await self._dao.commit()
        await self._dao.refresh(user)
        return user

    async def load_user_response(self, user: User) -> dict[str, object]:
        """Build a user response dict with auth methods."""
        methods = await self._dao.get_auth_methods(user.id)
        return {
            "id": user.id,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "is_superuser": user.is_superuser,
            "is_active": user.is_active,
            "auth_methods": [
                {"provider": m.provider, "email": m.email}
                for m in methods
            ],
        }

    async def link_auth_method(
        self, user: User, info: OAuthUserInfo
    ) -> dict[str, object]:
        """Link a new auth method to an existing user.

        Raises:
            ValueError: If the provider account is already linked.
        """
        existing = await self._dao.find_auth_method(
            info.provider, info.provider_id
        )
        if existing is not None:
            msg = "This provider account is already linked to a user"
            raise ValueError(msg)

        await self._dao.create_auth_method(
            user_id=user.id,
            provider=info.provider,
            provider_id=info.provider_id,
            email=info.email,
        )
        await self._dao.commit()
        return await self.load_user_response(user)
