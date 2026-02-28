"""Database heartbeat plugin — store latest heartbeat in Agent.last_health."""

from __future__ import annotations

from faros_server.plugins.contracts.heartbeat import HeartbeatPlugin
from faros_server.services.agent_service import AgentService


class DbHeartbeatPlugin(HeartbeatPlugin):
    """Store the latest heartbeat in the Agent.last_health column.

    Overwrites the previous value on every call — only the most recent
    heartbeat is retained.
    """

    def __init__(self, agent_service: AgentService) -> None:
        self._service = agent_service

    async def handle(self, agent_id: str, payload: dict[str, object]) -> None:
        """Overwrite Agent.last_health with the latest JSON."""
        await self._service.record_heartbeat(agent_id, payload)
