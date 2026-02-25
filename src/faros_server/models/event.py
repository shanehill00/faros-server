"""Agent anomaly event model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from faros_server.utils.db import Base


class AgentEvent(Base):
    """Anomaly event reported by an edge agent. Mirrors AnomalyEvent from the edge."""

    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[float] = mapped_column(Float)
    group: Mapped[str] = mapped_column(String(255))
    alert_state: Mapped[str] = mapped_column(String(32))
    raw_score: Mapped[float] = mapped_column(Float)
    ema_score: Mapped[float] = mapped_column(Float)
    per_channel_mse: Mapped[str] = mapped_column(Text)  # JSON list
    channel_names: Mapped[str] = mapped_column(Text)  # JSON list
    drift_triggered: Mapped[bool] = mapped_column(Boolean)
    spike_triggered: Mapped[bool] = mapped_column(Boolean)
    model_id: Mapped[str] = mapped_column(String(255))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
