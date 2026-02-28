"""Database event plugin — store anomaly events in agent_events table."""

from __future__ import annotations

from faros_server.plugins.event import EventPlugin
from faros_server.services.event_service import EventService


class DbEventPlugin(EventPlugin):
    """Store anomaly events in the agent_events table."""

    def __init__(self, event_service: EventService) -> None:
        self._service = event_service

    async def handle(
        self, agent_id: str, events: list[dict[str, object]],
    ) -> int:
        """Store a batch of anomaly events. Returns count stored."""
        return await self._service.record_events(agent_id, events)
