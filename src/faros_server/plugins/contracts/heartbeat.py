"""Heartbeat plugin contract — extensible agent heartbeat processing."""

from __future__ import annotations

from abc import ABC, abstractmethod


class HeartbeatPlugin(ABC):
    """Processes incoming agent heartbeats.

    Implementations decide what to do with heartbeat data — store it
    in the database, forward to Grafana/Datadog, or both.
    """

    @abstractmethod
    async def handle(self, agent_id: str, payload: dict[str, object]) -> None:
        """Process a heartbeat from an agent.

        Args:
            agent_id: The agent that sent the heartbeat.
            payload: Health data (cpu, memory, disk, group status).
        """
