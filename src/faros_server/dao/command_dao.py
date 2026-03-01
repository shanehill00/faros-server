"""Data access for AgentCommand model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from faros_server.models.command import AgentCommand

_active_conn: ContextVar[AsyncSession] = ContextVar("_command_dao_conn")


class CommandDAO:
    """Data access for agent commands.

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

    async def create_command(
        self,
        *,
        agent_id: str,
        command_type: str,
        payload: str | None,
    ) -> AgentCommand:
        """Insert a pending command for an agent."""
        command = AgentCommand(
            agent_id=agent_id,
            type=command_type,
            payload=payload,
        )
        self._conn().add(command)
        await self._conn().flush()
        return command

    async def list_pending(self, agent_id: str) -> list[AgentCommand]:
        """Return all pending commands for an agent, oldest first."""
        result = await self._conn().execute(
            select(AgentCommand)
            .where(
                AgentCommand.agent_id == agent_id,
                AgentCommand.status == "pending",
            )
            .order_by(AgentCommand.created_at),
        )
        return list(result.scalars().all())

    async def mark_in_progress(self, command_ids: list[str]) -> None:
        """Batch-update commands to in_progress with delivered_at timestamp."""
        now = datetime.now(timezone.utc)
        await self._conn().execute(
            sa_update(AgentCommand)
            .where(AgentCommand.id.in_(command_ids))
            .values(status="in_progress", delivered_at=now),
        )

    async def mark_expired(self, command_ids: list[str]) -> None:
        """Batch-update commands to expired with delivered_at timestamp."""
        now = datetime.now(timezone.utc)
        await self._conn().execute(
            sa_update(AgentCommand)
            .where(AgentCommand.id.in_(command_ids))
            .values(status="expired", delivered_at=now),
        )

    async def mark_acked(
        self,
        command: AgentCommand,
        result_json: str,
    ) -> None:
        """Mark a command as acked with its result."""
        command.status = "acked"
        command.result = result_json
        command.acked_at = datetime.now(timezone.utc)
        await self._conn().flush()

    async def find_by_id(self, command_id: str) -> AgentCommand | None:
        """Find a command by its ID."""
        result = await self._conn().execute(
            select(AgentCommand).where(AgentCommand.id == command_id),
        )
        return result.scalar_one_or_none()

    async def list_by_agent(
        self,
        agent_id: str,
        status: str | None = None,
    ) -> list[AgentCommand]:
        """List commands for an agent, optionally filtered by status."""
        stmt = select(AgentCommand).where(
            AgentCommand.agent_id == agent_id,
        )
        if status is not None:
            stmt = stmt.where(AgentCommand.status == status)
        stmt = stmt.order_by(AgentCommand.created_at)
        result = await self._conn().execute(stmt)
        return list(result.scalars().all())

    async def append_output(
        self,
        command: AgentCommand,
        text: str,
    ) -> None:
        """Concatenate text to a command's output buffer."""
        if command.output is None:
            command.output = text
        else:
            command.output += text
        await self._conn().flush()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn().commit()
