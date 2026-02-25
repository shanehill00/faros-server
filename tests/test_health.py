"""Tests for health check endpoint."""

from litestar.testing import TestClient


def test_health_returns_ok(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/health returns status ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
