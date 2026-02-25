"""Health check endpoint."""

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Return server health status."""
    return {"status": "ok"}
