"""WebSocket transport — same resources, different protocol."""

from __future__ import annotations

from typing import Any

from litestar import WebSocket, websocket
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

from faros_server.dao.user_dao import UserDAO
from faros_server.models.user import User
from faros_server.resources.auth import AuthResource
from faros_server.utils.jwt import JWTManager


class WebSocketHandler:
    """Stateful per-connection handler. Authenticates once, then dispatches actions."""

    def __init__(
        self,
        socket: WebSocket[object, object, State],
        jwt_manager: JWTManager,
        user_dao: UserDAO,
        auth_resource: AuthResource,
    ) -> None:
        self._socket = socket
        self._jwt_manager = jwt_manager
        self._user_dao = user_dao
        self._auth_resource = auth_resource
        self._current_user: User | None = None

    async def authenticate(self, token: str) -> User | None:
        """Validate a JWT token and return the user, or None on failure."""
        try:
            return await self._jwt_manager.resolve_user(token, self._user_dao)
        except ValueError:
            return None

    async def dispatch(self, action: str) -> dict[str, Any]:
        """Route an action to the appropriate resource method."""
        assert self._current_user is not None
        if action == "auth.me":
            result = await self._auth_resource.me(self._current_user)
            return {"action": action, "data": result}

        return {
            "action": action,
            "error": {"code": 400, "detail": f"Unknown action: {action}"},
        }

    async def refresh_user(self) -> bool:
        """Re-fetch the current user from the database. Returns False if invalid."""
        assert self._current_user is not None
        async with self._user_dao.transaction():
            user = await self._user_dao.find_by_id(self._current_user.id)
        if user is None or not user.is_active:
            return False
        self._current_user = user
        return True

    async def run(self) -> None:
        """Main connection loop: accept, authenticate, then dispatch actions."""
        await self._socket.accept()

        try:
            while True:
                message = await self._socket.receive_json()
                action: str = message.get("action", "")

                # First message must include a token
                if self._current_user is None:
                    token = message.get("token", "")
                    if not token:
                        await self._socket.send_json(
                            {"action": action, "error": {"code": 401, "detail": "Token required"}}
                        )
                        continue

                    user = await self.authenticate(token)
                    if user is None:
                        await self._socket.send_json(
                            {"action": action, "error": {"code": 401, "detail": "Invalid token"}}
                        )
                        await self._socket.close(code=4001, reason="Authentication failed")
                        return

                    self._current_user = user

                    if not action:
                        await self._socket.send_json(
                            {"action": "auth", "data": {"status": "ok"}}
                        )
                        continue

                # Re-validate user on every dispatch (may have been deactivated)
                if not await self.refresh_user():
                    error = {"code": 401, "detail": "User not found or inactive"}
                    await self._socket.send_json({"action": action, "error": error})
                    await self._socket.close(code=4001, reason="User invalid")
                    return

                response = await self.dispatch(action)
                await self._socket.send_json(response)

        except WebSocketDisconnect:
            pass


@websocket("/ws")
async def websocket_endpoint(socket: WebSocket[object, object, State]) -> None:
    """Handle WebSocket connections with JSON message dispatch."""
    handler = WebSocketHandler(
        socket=socket,
        jwt_manager=socket.app.state.jwt,
        user_dao=socket.app.state.dao,
        auth_resource=socket.app.state.auth,
    )
    await handler.run()
