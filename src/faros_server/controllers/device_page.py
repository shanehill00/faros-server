"""Device approval page controller — browser-facing HTML for device-flow registration."""

from __future__ import annotations

import html

from litestar import Controller, Request, get
from litestar.datastructures import State
from litestar.response import Redirect, Response

from faros_server.models.user import User
from faros_server.resources.agent import (
    AgentResource,
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
_DENIED_HTML = load_template("denied.html")
_ERROR_HTML = load_template("error.html")


class DevicePageController(Controller):
    """Browser-facing HTML controller for device-flow approval."""

    path = "/api/agents/device"

    @staticmethod
    async def _try_resolve_user(
        request: Request[object, object, State], token: str, auth: AuthResource,
    ) -> tuple[User, str] | None:
        """Resolve user from query param token, Authorization header, or cookie.

        Returns (user, token_string) or None if no valid auth found.
        """
        if not token:
            header = request.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                token = header[len("Bearer "):]
        if not token:
            token = request.cookies.get("faros_token", "")
        if not token:
            return None
        try:
            user = await auth.resolve_token(token)
        except ValueError:
            return None
        return user, token

    @staticmethod
    def _render(title: str, body: str) -> str:
        """Render body content into the base HTML template."""
        return _BASE_HTML.safe_substitute(title=html.escape(title), body=body)

    @staticmethod
    def _approval_page(info: dict[str, str], token: str) -> str:
        """Render the approval page or already-registered page."""
        agent_name = html.escape(info["agent_name"])
        robot_type = html.escape(info["robot_type"])
        user_code = html.escape(info["user_code"])
        status = info.get("status", "pending")

        if status == "denied":
            body = _DENIED_HTML.safe_substitute(agent_name=agent_name)
            return DevicePageController._render("Registration Denied", body)

        if status != "pending":
            body = _ALREADY_REGISTERED_HTML.safe_substitute(agent_name=agent_name)
            return DevicePageController._render("Agent Already Registered", body)

        safe_token = html.escape(token, quote=True)
        body = _APPROVAL_HTML.safe_substitute(
            agent_name=agent_name,
            robot_type=robot_type,
            user_code=user_code,
            token=safe_token,
        )
        return DevicePageController._render("Approve Agent Registration", body)

    @staticmethod
    def _error_page(message: str) -> str:
        """Render an error page."""
        body = _ERROR_HTML.safe_substitute(message=html.escape(message))
        return DevicePageController._render("Error", body)

    @get("/{user_code:str}", media_type="text/html")
    async def device_page(
        self,
        user_code: str,
        request: Request[object, object, State],
        agent_resource: AgentResource,
        auth: AuthResource,
        token: str = "",
    ) -> Response[str] | Redirect:
        """HTML approval page for device-flow registration."""
        resolved = await self._try_resolve_user(request, token, auth)
        if resolved is None:
            next_path = f"/api/agents/device/{user_code}"
            try:
                login_url = auth.device_login_url("google", next_path)
            except (UnsupportedProviderError, OAuthNotConfiguredError):
                return Response(
                    content=self._error_page("OAuth not configured."),
                    status_code=500,
                    media_type="text/html",
                )
            return Redirect(path=login_url, status_code=302)
        _user, resolved_token = resolved
        try:
            info = await agent_resource.device_page(user_code)
        except DeviceFlowNotFoundError:
            return Response(
                content=self._error_page("Unknown device code."),
                status_code=404,
                media_type="text/html",
            )
        except DeviceFlowExpiredError:
            return Response(
                content=self._error_page("Device code expired."),
                status_code=410,
                media_type="text/html",
            )
        return Response(
            content=self._approval_page(info, resolved_token),
            status_code=200,
            media_type="text/html",
        )
