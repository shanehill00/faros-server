"""Timezone helpers."""

from __future__ import annotations

from datetime import datetime, timezone


class Time:
    """Static helpers for datetime normalization."""

    @staticmethod
    def ensure_utc(dt: datetime) -> datetime:
        """Ensure a datetime is UTC-aware. SQLite may strip timezone info."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
