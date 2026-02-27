"""Agent controller — thin HTTP adapter for AgentResource."""

from __future__ import annotations

import html

from litestar import Controller, Request, delete, get, post
from litestar.datastructures import State
from litestar.exceptions import HTTPException, NotAuthorizedException
from litestar.response import Redirect, Response

from faros_server.dao.user_dao import UserDAO
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
from faros_server.utils.jwt import JWTManager


async def _try_resolve_user(
    request: Request[object, object, State], token: str,
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
    user_dao: UserDAO = request.app.state.dao
    try:
        user = await JWTManager.resolve_user(token, user_dao)
    except ValueError:
        return None
    return user, token


def _page_html(title: str, body: str) -> str:
    """Wrap body content in a minimal HTML page."""
    return (
        "<!DOCTYPE html><html><head>"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:480px;"
        "margin:60px auto;padding:0 20px;color:#1a1a1a}"
        "h1{font-size:1.4em}"
        ".info{background:#f5f5f5;padding:16px;border-radius:8px;margin:16px 0}"
        ".info dt{font-weight:600;margin-top:8px}"
        ".info dd{margin:2px 0 0 0;color:#555}"
        "button{background:#2563eb;color:#fff;border:none;padding:10px 28px;"
        "border-radius:6px;font-size:1em;cursor:pointer;margin-right:8px}"
        "button:hover{background:#1d4ed8}"
        "button.deny{background:#dc2626}"
        "button.deny:hover{background:#b91c1c}"
        "#result{margin-top:16px;font-weight:600}"
        ".error{color:#dc2626}"
        ".success{color:#16a34a}"
        "</style></head><body>"
        f"{body}"
        "</body></html>"
    )


def _approval_html(info: dict[str, str], token: str) -> str:
    """Build the approval page HTML with embedded JS for the approve POST."""
    agent_name = html.escape(info["agent_name"])
    robot_type = html.escape(info["robot_type"])
    user_code = html.escape(info["user_code"])
    status = info.get("status", "pending")

    if status != "pending":
        return _page_html(
            "Agent Already Registered",
            f"<h1>Agent Already Registered</h1>"
            f"<p>The agent <strong>{agent_name}</strong> has already been "
            f"registered.</p>",
        )

    safe_token = html.escape(token, quote=True)
    safe_user_code = html.escape(info["user_code"], quote=True)
    return _page_html(
        "Approve Agent Registration",
        f"<h1>Approve Agent Registration</h1>"
        f"<dl class=\"info\">"
        f"<dt>Agent Name</dt><dd>{agent_name}</dd>"
        f"<dt>Robot Type</dt><dd>{robot_type}</dd>"
        f"<dt>Device Code</dt><dd>{user_code}</dd>"
        f"</dl>"
        f"<button id=\"approve\" onclick=\"approve()\">Approve</button>"
        f"<button class=\"deny\" id=\"deny\" onclick=\"deny()\">Deny</button>"
        f"<div id=\"result\"></div>"
        f"<script>"
        f"const token='{safe_token}';"
        f"const userCode='{safe_user_code}';"
        f"async function approve(){{"
        f"document.getElementById('approve').disabled=true;"
        f"document.getElementById('deny').disabled=true;"
        f"try{{"
        f"const r=await fetch('/api/agents/device/approve',{{"
        f"method:'POST',"
        f"headers:{{'Authorization':'Bearer '+token,"
        f"'Content-Type':'application/json'}},"
        f"body:JSON.stringify({{user_code:userCode}})}});"
        f"const d=await r.json();"
        f"if(r.ok){{document.getElementById('result').innerHTML="
        f"'<span class=\"success\">Agent registered! You can close this tab.</span>';}}"
        f"else{{document.getElementById('result').innerHTML="
        f"'<span class=\"error\">Error: '+(d.detail||'Unknown error')+'</span>';"
        f"document.getElementById('approve').disabled=false;"
        f"document.getElementById('deny').disabled=false;}}"
        f"}}catch(e){{document.getElementById('result').innerHTML="
        f"'<span class=\"error\">Network error.</span>';"
        f"document.getElementById('approve').disabled=false;"
        f"document.getElementById('deny').disabled=false;}}}}"
        f"function deny(){{"
        f"document.getElementById('result').innerHTML="
        f"'<span class=\"error\">Registration denied. You can close this tab.</span>';"
        f"document.getElementById('approve').disabled=true;"
        f"document.getElementById('deny').disabled=true;}}"
        f"</script>",
    )


def _error_html(message: str) -> str:
    """Build an error page HTML."""
    return _page_html("Error", f"<h1>Error</h1><p>{html.escape(message)}</p>")


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
        resolved = await _try_resolve_user(request, token)
        if resolved is None:
            next_path = f"/api/agents/device/{user_code}"
            try:
                login_url = auth.device_login_url("google", next_path)
            except (UnsupportedProviderError, OAuthNotConfiguredError):
                return Response(
                    content=_error_html("OAuth not configured."),
                    status_code=500,
                    media_type="text/html",
                )
            return Redirect(path=login_url, status_code=302)
        _user, resolved_token = resolved
        try:
            info = await agent_resource.device_page(user_code)
        except DeviceFlowNotFoundError:
            return Response(
                content=_error_html("Unknown device code."),
                status_code=404,
                media_type="text/html",
            )
        except DeviceFlowExpiredError:
            return Response(
                content=_error_html("Device code expired."),
                status_code=410,
                media_type="text/html",
            )
        return Response(
            content=_approval_html(info, resolved_token),
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
