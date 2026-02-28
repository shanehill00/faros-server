"""Data access for AgentEvent model."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from faros_server.models.event import AgentEvent

_active_conn: ContextVar[AsyncSession] = ContextVar("_event_dao_conn")


class EventDAO:
    """Data access for anomaly events.

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

    async def create_event(
        self,
        *,
        agent_id: str,
        trace_id: str,
        timestamp: float,
        group: str,
        alert_state: str,
        raw_score: float,
        ema_score: float,
        per_channel_mse: list[float],
        channel_names: list[str],
        drift_triggered: bool,
        spike_triggered: bool,
        model_id: str,
    ) -> AgentEvent:
        """Insert a single anomaly event."""
        event = AgentEvent(
            agent_id=agent_id,
            trace_id=trace_id,
            timestamp=timestamp,
            group=group,
            alert_state=alert_state,
            raw_score=raw_score,
            ema_score=ema_score,
            per_channel_mse=json.dumps(per_channel_mse),
            channel_names=json.dumps(channel_names),
            drift_triggered=drift_triggered,
            spike_triggered=spike_triggered,
            model_id=model_id,
            received_at=datetime.now(timezone.utc),
        )
        self._conn().add(event)
        await self._conn().flush()
        return event

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn().commit()
