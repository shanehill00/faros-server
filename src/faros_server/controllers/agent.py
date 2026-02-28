"""Agent controller — device flow and user-facing agent management."""

from __future__ import annotations

from litestar import Controller, delete, get, post
from litestar.exceptions import HTTPException, NotAuthorizedException

from faros_server.models.user import User
from faros_server.resources.agent import (
    AgentNotFoundError,
    AgentNotOwnedError,
    AgentResource,
    DeviceFlowAlreadyUsedError,
    DeviceFlowExpiredError,
    DeviceFlowNotFoundError,
)


class AgentController(Controller):
    """Device flow and user-facing agent management (JWT auth)."""

    path = "/api/agents"

    @post("/device/start", status_code=201)
    async def start_device_flow(
        self,
        data: dict[str, str],
        agent_resource: AgentResource,
    ) -> dict[str, str | int]:
        """Agent initiates device-flow registration.

        Body: {"agent_name": "...", "robot_type": "..."}
        """
        agent_name = data.get("agent_name", "").strip()
        robot_type = data.get("robot_type", "").strip()
        if not agent_name or not robot_type:
            raise HTTPException(
                status_code=400,
                detail="agent_name and robot_type are required",
            )
        return await agent_resource.start_device_flow(agent_name, robot_type)

    @post("/device/poll", status_code=200)
    async def poll_device_flow(
        self,
        data: dict[str, str],
        agent_resource: AgentResource,
    ) -> dict[str, str]:
        """Agent polls for approval status.

        Body: {"device_code": "..."}
        """
        device_code = data.get("device_code", "").strip()
        if not device_code:
            raise HTTPException(
                status_code=400, detail="device_code is required",
            )
        try:
            return await agent_resource.poll_device_flow(device_code)
        except DeviceFlowNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error

    @post("/device/approve", status_code=200)
    async def approve_device(
        self,
        data: dict[str, str],
        user: User,
        agent_resource: AgentResource,
    ) -> dict[str, str]:
        """Operator approves a pending device registration.

        Body: {"user_code": "XXXX-XXXX"}
        """
        user_code = data.get("user_code", "").strip()
        if not user_code:
            raise HTTPException(
                status_code=400, detail="user_code is required",
            )
        try:
            return await agent_resource.approve_device(user_code, user)
        except DeviceFlowNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error
        except DeviceFlowExpiredError as error:
            raise HTTPException(
                status_code=410, detail=str(error),
            ) from error
        except DeviceFlowAlreadyUsedError as error:
            raise HTTPException(
                status_code=409, detail=str(error),
            ) from error

    @post("/device/deny", status_code=200)
    async def deny_device(
        self,
        data: dict[str, str],
        user: User,
        agent_resource: AgentResource,
    ) -> dict[str, str]:
        """Operator denies a pending device registration.

        Body: {"user_code": "XXXX-XXXX"}
        """
        user_code = data.get("user_code", "").strip()
        if not user_code:
            raise HTTPException(
                status_code=400, detail="user_code is required",
            )
        try:
            return await agent_resource.deny_device(user_code, user)
        except DeviceFlowNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error
        except DeviceFlowExpiredError as error:
            raise HTTPException(
                status_code=410, detail=str(error),
            ) from error
        except DeviceFlowAlreadyUsedError as error:
            raise HTTPException(
                status_code=409, detail=str(error),
            ) from error

    @get("/")
    async def list_agents(
        self,
        user: User,
        agent_resource: AgentResource,
    ) -> list[dict[str, object]]:
        """List all agents owned by the authenticated user."""
        return await agent_resource.list_agents(user)

    @delete("/{agent_id:str}/key", status_code=200)
    async def revoke_key(
        self,
        agent_id: str,
        user: User,
        agent_resource: AgentResource,
    ) -> dict[str, int]:
        """Revoke all API keys for an agent."""
        try:
            return await agent_resource.revoke_key(agent_id, user)
        except AgentNotFoundError as error:
            raise HTTPException(
                status_code=404, detail=str(error),
            ) from error
        except AgentNotOwnedError as error:
            raise NotAuthorizedException(detail=str(error)) from error
