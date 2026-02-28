"""Anomaly plugin contract — extensible anomaly event processing."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AnomalyPlugin(ABC):
    """Processes incoming agent anomaly events.

    Implementations decide what to do with anomaly data — store it
    in the database, forward to analytics, or both.
    """

    @abstractmethod
    async def handle(
        self, agent_id: str, anomalies: list[dict[str, object]],
    ) -> int:
        """Process a batch of anomaly events from an agent.

        Args:
            agent_id: The agent that sent the anomalies.
            anomalies: List of anomaly event dicts.

        Returns:
            Count of anomalies stored.
        """
