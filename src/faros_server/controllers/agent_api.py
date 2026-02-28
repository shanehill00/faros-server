"""Agent API controller — API-key-authed endpoints for edge agents."""

from __future__ import annotations

from litestar import Controller, Request, post
from litestar.datastructures import State
from litestar.di import Provide
from litestar.exceptions import NotAuthorizedException
from litestar.types import Dependencies

from faros_server.models.agent import Agent
from faros_server.resources.agent import AgentNotFoundError, AgentResource


async def _provide_agent_from_api_key(
    request: Request[object, object, State],
    agent_resource: AgentResource,
) -> Agent:
    """Extract Bearer API key and resolve to an Agent.

    Raises:
        NotAuthorizedException: If the header is missing, malformed,
            or the key does not map to an agent.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise NotAuthorizedException(
            detail="Missing or invalid Authorization header",
        )
    api_key = header[len("Bearer "):]
    try:
        return await agent_resource.resolve_agent(api_key)
    except AgentNotFoundError as error:
        raise NotAuthorizedException(detail=str(error)) from error


class AgentApiController(Controller):
    """API-key-authed endpoints called by edge agents."""

    path = "/api/agents"
    # Litestar declares dependencies as an instance var, so ClassVar
    # would fail mypy.  Suppress RUF012 (mutable class attribute).
    dependencies: Dependencies = {  # noqa: RUF012
        "agent": Provide(_provide_agent_from_api_key),
    }

    @post("/anomalies", status_code=201)
    async def post_anomalies(
        self,
        data: list[dict[str, object]],
        agent: Agent,
        agent_resource: AgentResource,
    ) -> dict[str, int]:
        """Agent posts a batch of anomaly events."""
        return await agent_resource.record_anomalies(agent, data)

    @post("/heartbeat", status_code=200)
    async def heartbeat(
        self,
        data: dict[str, object],
        agent: Agent,
        agent_resource: AgentResource,
    ) -> dict[str, str]:
        """Agent sends a heartbeat."""
        return await agent_resource.record_heartbeat(agent, data)

    @post("/logout", status_code=200)
    async def agent_logout(
        self,
        agent: Agent,
        agent_resource: AgentResource,
    ) -> dict[str, int]:
        """Agent revokes its own API keys."""
        return await agent_resource.agent_logout(agent)
