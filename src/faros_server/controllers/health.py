"""Health check controller — thin HTTP adapter."""

from __future__ import annotations

from litestar import Controller, get

from faros_server.resources.health import HealthResource


class HealthController(Controller):
    """HTTP adapter for health checks."""

    path = "/api"

    @get("/health")
    async def health(self, health_resource: HealthResource) -> dict[str, str]:
        """Return server health status."""
        return health_resource.check()
