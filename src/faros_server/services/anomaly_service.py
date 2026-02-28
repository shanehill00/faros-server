"""Business logic for anomaly event ingestion."""

from __future__ import annotations

from typing import Any

from faros_server.dao.anomaly_dao import AnomalyDAO


class AnomalyService:
    """Built once at startup with its DAO pre-wired."""

    def __init__(self, anomaly_dao: AnomalyDAO) -> None:
        self._dao = anomaly_dao

    async def record_anomalies(
        self, agent_id: str, anomalies: list[dict[str, Any]],
    ) -> int:
        """Store a batch of anomaly events.

        Each anomaly dict must contain the 11 AnomalyEvent fields:
        trace_id, timestamp, group, alert_state, raw_score, ema_score,
        per_channel_mse, channel_names, drift_triggered, spike_triggered,
        model_id.

        Returns:
            Count of anomalies stored.
        """
        if not anomalies:
            return 0

        async with self._dao.transaction():
            for anomaly in anomalies:
                await self._dao.create_anomaly(
                    agent_id=agent_id,
                    trace_id=str(anomaly["trace_id"]),
                    timestamp=float(anomaly["timestamp"]),
                    group=str(anomaly["group"]),
                    alert_state=str(anomaly["alert_state"]),
                    raw_score=float(anomaly["raw_score"]),
                    ema_score=float(anomaly["ema_score"]),
                    per_channel_mse=list(anomaly["per_channel_mse"]),
                    channel_names=list(anomaly["channel_names"]),
                    drift_triggered=bool(anomaly["drift_triggered"]),
                    spike_triggered=bool(anomaly["spike_triggered"]),
                    model_id=str(anomaly["model_id"]),
                )
            await self._dao.commit()

        return len(anomalies)
