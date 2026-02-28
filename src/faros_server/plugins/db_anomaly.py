"""Database anomaly plugin — store anomaly events in agent_events table."""

from __future__ import annotations

from faros_server.plugins.anomaly import AnomalyPlugin
from faros_server.services.anomaly_service import AnomalyService


class DbAnomalyPlugin(AnomalyPlugin):
    """Store anomaly events in the agent_events table."""

    def __init__(self, anomaly_service: AnomalyService) -> None:
        self._service = anomaly_service

    async def handle(
        self, agent_id: str, anomalies: list[dict[str, object]],
    ) -> int:
        """Store a batch of anomaly events. Returns count stored."""
        return await self._service.record_anomalies(agent_id, anomalies)
