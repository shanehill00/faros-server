"""Agent, API key, and device registration models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from faros_server.db import Base


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def _uuid() -> str:
    """Generate a new UUID hex string."""
    return uuid.uuid4().hex


class Agent(Base):
    """Registered edge agent."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    robot_type: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="registered")
    last_health: Mapped[str | None] = mapped_column(Text, nullable=True)


class ApiKey(Base):
    """API key for agent authentication. Only the SHA-256 hash is stored."""

    __tablename__ = "api_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class DeviceRegistration(Base):
    """Pending device-flow registration. Agent polls until operator approves."""

    __tablename__ = "device_registrations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    device_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(255))
    robot_type: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    api_key_plaintext: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
