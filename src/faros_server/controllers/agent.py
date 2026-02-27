"""Agent controller — thin HTTP adapter for AgentResource."""

from __future__ import annotations

import html

from litestar import Controller, Request, delete, get, post
from litestar.datastructures import State
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.response import Redirect, Response

from faros_server.models.user import User
from faros_server.resources.agent import (
    AgentNotFoundError,
    AgentNotOwnedError,
    AgentResource,
    DeviceFlowAlreadyUsedError,
    DeviceFlowExpiredError,
    DeviceFlowNotFoundError,
)
from faros_server.resources.auth import (
    AuthResource,
    OAuthNotConfiguredError,
    UnsupportedProviderError,
)
from faros_server.templates import load_template

_BASE_HTML = load_template("base.html")
_APPROVAL_HTML = load_template("approval.html")
_ALREADY_REGISTERED_HTML = load_template("already_registered.html")
_ERROR_HTML = load_template("error.html")


async def _try_resolve_user(
    request: Request[object, object, State], token: str, auth: AuthResource,
) -> tuple[User, str] | None:
    """Resolve user from query param token or Authorization header.

    Returns (user, token_string) or None if no valid auth found.
    """
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):]
    if not token:
        return None
    try:
        user = await auth.resolve_token(token)
    except ValueError:
        return None
    return user, token


def _render(title: str, body: str) -> str:
    """Render body content into the base HTML template."""
    return _BASE_HTML.safe_substitute(title=html.escape(title), body=body)


def _approval_page(info: dict[str, str], token: str) -> str:
    """Render the approval page or already-registered page."""
    agent_name = html.escape(info["agent_name"])
    robot_type = html.escape(info["robot_type"])
    user_code = html.escape(info["user_code"])
    status = info.get("status", "pending")

    if status != "pending":
        body = _ALREADY_REGISTERED_HTML.safe_substitute(agent_name=agent_name)
        return _render("Agent Already Registered", body)

    safe_token = html.escape(token, quote=True)
    body = _APPROVAL_HTML.safe_substitute(
        agent_name=agent_name,
        robot_type=robot_type,
        user_code=user_code,
        token=safe_token,
    )
    return _render("Approve Agent Registration", body)


def _error_page(message: str) -> str:
    """Render an error page."""
    body = _ERROR_HTML.safe_substitute(message=html.escape(message))
    return _render("Error", body)


class AgentController(Controller):
    """HTTP adapter for agent registration and management."""

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

    @get("/device/{user_code:str}", media_type="text/html")
    async def device_page(
        self,
        user_code: str,
        request: Request[object, object, State],
        agent_resource: AgentResource,
        auth: AuthResource,
        token: str = "",
    ) -> Response[str] | Redirect:
        """HTML approval page for device-flow registration."""
        resolved = await _try_resolve_user(request, token, auth)
        if resolved is None:
            next_path = f"/api/agents/device/{user_code}"
            try:
                login_url = auth.device_login_url("google", next_path)
            except (UnsupportedProviderError, OAuthNotConfiguredError):
                return Response(
                    content=_error_page("OAuth not configured."),
                    status_code=500,
                    media_type="text/html",
                )
            return Redirect(path=login_url, status_code=302)
        _user, resolved_token = resolved
        try:
            info = await agent_resource.device_page(user_code)
        except DeviceFlowNotFoundError:
            return Response(
                content=_error_page("Unknown device code."),
                status_code=404,
                media_type="text/html",
            )
        except DeviceFlowExpiredError:
            return Response(
                content=_error_page("Device code expired."),
                status_code=410,
                media_type="text/html",
            )
        return Response(
            content=_approval_page(info, resolved_token),
            status_code=200,
            media_type="text/html",
        )

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
