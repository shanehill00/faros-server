"""Health check controller."""

from __future__ import annotations

from litestar import Controller, get


class HealthController(Controller):
    """Health check endpoint."""

    path = "/api"

    @get("/health")
    async def health(self) -> dict[str, str]:
        """Return server health status."""
        return {"status": "ok"}
