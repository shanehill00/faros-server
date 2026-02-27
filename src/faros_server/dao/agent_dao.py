"""Data access for Agent, ApiKey, and DeviceRegistration models."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from faros_server.models.agent import Agent, ApiKey, DeviceRegistration

_active_conn: ContextVar[AsyncSession] = ContextVar("_agent_dao_conn")


class AgentDAO:
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

    # --- DeviceRegistration ---

    async def create_device_registration(
        self,
        *,
        device_code: str,
        user_code: str,
        agent_name: str,
        robot_type: str,
        expires_at: datetime,
    ) -> DeviceRegistration:
        """Insert a new pending device registration."""
        reg = DeviceRegistration(
            device_code=device_code,
            user_code=user_code,
            agent_name=agent_name,
            robot_type=robot_type,
            expires_at=expires_at,
        )
        self._conn().add(reg)
        await self._conn().flush()
        return reg

    async def find_registration_by_device_code(
        self, device_code: str,
    ) -> DeviceRegistration | None:
        """Find a device registration by its device code."""
        result = await self._conn().execute(
            select(DeviceRegistration).where(
                DeviceRegistration.device_code == device_code,
            )
        )
        return result.scalar_one_or_none()

    async def find_registration_by_user_code(
        self, user_code: str,
    ) -> DeviceRegistration | None:
        """Find a device registration by its user code."""
        result = await self._conn().execute(
            select(DeviceRegistration).where(
                DeviceRegistration.user_code == user_code,
            )
        )
        return result.scalar_one_or_none()

    # --- Agent ---

    async def create_agent(
        self,
        *,
        name: str,
        robot_type: str,
        owner_id: str,
    ) -> Agent:
        """Insert a new agent and flush to populate its id."""
        agent = Agent(
            name=name,
            robot_type=robot_type,
            owner_id=owner_id,
        )
        self._conn().add(agent)
        await self._conn().flush()
        return agent

    async def find_agent_by_name(self, name: str) -> Agent | None:
        """Find an agent by unique name."""
        result = await self._conn().execute(
            select(Agent).where(Agent.name == name)
        )
        return result.scalar_one_or_none()

    async def find_agent_by_id(self, agent_id: str) -> Agent | None:
        """Find an agent by primary key."""
        result = await self._conn().execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def list_agents_by_owner(self, owner_id: str) -> list[Agent]:
        """Return all agents owned by a user."""
        result = await self._conn().execute(
            select(Agent).where(Agent.owner_id == owner_id)
        )
        return list(result.scalars())

    async def update_agent_last_seen(self, agent_id: str) -> None:
        """Touch the last_seen_at timestamp."""
        await self._conn().execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(last_seen_at=datetime.now(timezone.utc))
        )

    # --- ApiKey ---

    async def create_api_key(
        self,
        *,
        key_hash: str,
        agent_id: str,
    ) -> ApiKey:
        """Insert a new API key (hashed)."""
        api_key = ApiKey(
            key_hash=key_hash,
            agent_id=agent_id,
        )
        self._conn().add(api_key)
        return api_key

    async def find_api_key_by_hash(self, key_hash: str) -> ApiKey | None:
        """Find an API key by its SHA-256 hash."""
        result = await self._conn().execute(
            select(ApiKey).where(
                ApiKey.key_hash == key_hash,
                ApiKey.revoked == False,  # noqa: E712 — SQLAlchemy comparison
            )
        )
        return result.scalar_one_or_none()

    async def revoke_api_keys_for_agent(self, agent_id: str) -> int:
        """Revoke all API keys for an agent. Returns count revoked."""
        result = await self._conn().execute(
            update(ApiKey)
            .where(ApiKey.agent_id == agent_id, ApiKey.revoked == False)  # noqa: E712
            .values(revoked=True)
        )
        return cast(CursorResult[Any], result).rowcount

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn().commit()
