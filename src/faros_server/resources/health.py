"""Health resource — protocol-agnostic health check logic."""

from __future__ import annotations


class HealthResource:
    """Health check operations."""

    def check(self) -> dict[str, str]:
        """Return current server health status."""
        return {"status": "ok"}
