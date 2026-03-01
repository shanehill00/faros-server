"""Agent API controller — API-key-authed endpoints for edge agents."""

from __future__ import annotations

from typing import Any

from litestar import Controller, Request, get, post
from litestar.datastructures import State
from litestar.di import Provide
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.types import Dependencies

from faros_server.models.agent import Agent
from faros_server.resources.agent import (
    AgentNotFoundError,
    AgentResource,
    CommandAlreadyAckedError,
    CommandNotFoundError,
    CommandNotInProgressError,
)


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

    @get("/commands", status_code=200)
    async def poll_commands(
        self,
        agent: Agent,
        agent_resource: AgentResource,
    ) -> list[dict[str, Any]]:
        """Agent polls for pending commands."""
        return await agent_resource.poll_commands(agent)

    @post("/commands/{command_id:str}/ack", status_code=200)
    async def ack_command(
        self,
        command_id: str,
        data: dict[str, Any],
        agent: Agent,
        agent_resource: AgentResource,
    ) -> dict[str, Any]:
        """Agent acknowledges a command with its result."""
        try:
            return await agent_resource.ack_command(agent, command_id, data)
        except CommandNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error
        except CommandAlreadyAckedError as error:
            raise HTTPException(
                status_code=409, detail=str(error),
            ) from error

    @post("/commands/{command_id:str}/output", status_code=200)
    async def append_output(
        self,
        command_id: str,
        data: dict[str, Any],
        agent: Agent,
        agent_resource: AgentResource,
    ) -> dict[str, str]:
        """Agent appends output lines to an in-progress command."""
        output = data.get("output")
        if not isinstance(output, str) or not output:
            raise HTTPException(
                status_code=400,
                detail="'output' must be a non-empty string",
            )
        try:
            return await agent_resource.append_command_output(
                agent, command_id, output,
            )
        except CommandNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error
        except CommandNotInProgressError as error:
            raise HTTPException(
                status_code=409, detail=str(error),
            ) from error
