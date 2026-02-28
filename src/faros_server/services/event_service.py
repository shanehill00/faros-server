"""Business logic for anomaly event ingestion."""

from __future__ import annotations

from typing import Any

from faros_server.dao.event_dao import EventDAO


class EventService:
    """Built once at startup with its DAO pre-wired."""

    def __init__(self, event_dao: EventDAO) -> None:
        self._dao = event_dao

    async def record_events(
        self, agent_id: str, events: list[dict[str, Any]],
    ) -> int:
        """Store a batch of anomaly events.

        Each event dict must contain the 11 AnomalyEvent fields:
        trace_id, timestamp, group, alert_state, raw_score, ema_score,
        per_channel_mse, channel_names, drift_triggered, spike_triggered,
        model_id.

        Returns:
            Count of events stored.
        """
        if not events:
            return 0

        async with self._dao.transaction():
            for event in events:
                await self._dao.create_event(
                    agent_id=agent_id,
                    trace_id=str(event["trace_id"]),
                    timestamp=float(event["timestamp"]),
                    group=str(event["group"]),
                    alert_state=str(event["alert_state"]),
                    raw_score=float(event["raw_score"]),
                    ema_score=float(event["ema_score"]),
                    per_channel_mse=list(event["per_channel_mse"]),
                    channel_names=list(event["channel_names"]),
                    drift_triggered=bool(event["drift_triggered"]),
                    spike_triggered=bool(event["spike_triggered"]),
                    model_id=str(event["model_id"]),
                )
            await self._dao.commit()

        return len(events)
