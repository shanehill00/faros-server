"""Event plugin contract — extensible agent event processing."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EventPlugin(ABC):
    """Processes incoming agent anomaly events.

    Implementations decide what to do with event data — store it
    in the database, forward to analytics, or both.
    """

    @abstractmethod
    async def handle(
        self, agent_id: str, events: list[dict[str, object]],
    ) -> int:
        """Process a batch of anomaly events from an agent.

        Args:
            agent_id: The agent that sent the events.
            events: List of anomaly event dicts.

        Returns:
            Count of events stored.
        """
