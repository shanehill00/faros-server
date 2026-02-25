"""WebSocket transport — same resources, different protocol."""

from __future__ import annotations

from typing import Any

from litestar import WebSocket, websocket
from litestar.datastructures import State
from litestar.exceptions import WebSocketDisconnect

from faros_server.dao.user_dao import UserDAO
from faros_server.resources.auth import AuthResource
from faros_server.utils.jwt import JWTManager


async def _authenticate(
    token: str, jwt: JWTManager, dao: UserDAO
) -> dict[str, Any] | None:
    """Validate a JWT token and return context, or None on failure."""
    try:
        user = await jwt.resolve_user(token, dao)
    except ValueError:
        return None
    return {"user_id": user.id, "user": user}


async def _dispatch(
    action: str,
    auth: AuthResource,
    dao: UserDAO,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Route an action to the appropriate resource method."""
    if action == "auth.me":
        result = await auth.me(ctx["user"])
        return {"action": action, "data": result}

    return {
        "action": action,
        "error": {"code": 400, "detail": f"Unknown action: {action}"},
    }


@websocket("/ws")
async def websocket_endpoint(socket: WebSocket[object, object, State]) -> None:
    """Handle WebSocket connections with JSON message dispatch."""
    await socket.accept()

    jwt: JWTManager = socket.app.state.jwt
    dao: UserDAO = socket.app.state.dao
    auth: AuthResource = socket.app.state.auth
    ctx: dict[str, Any] | None = None

    try:
        while True:
            msg = await socket.receive_json()
            action: str = msg.get("action", "")

            # First message must authenticate
            if ctx is None:
                token = msg.get("token", "")
                if not token:
                    await socket.send_json(
                        {"action": action, "error": {"code": 401, "detail": "Token required"}}
                    )
                    continue

                ctx = await _authenticate(token, jwt, dao)

                if ctx is None:
                    await socket.send_json(
                        {"action": action, "error": {"code": 401, "detail": "Invalid token"}}
                    )
                    await socket.close(code=4001, reason="Authentication failed")
                    return

                if not action:
                    await socket.send_json({"action": "auth", "data": {"status": "ok"}})
                    continue

            # Authenticated — refresh user and dispatch
            async with dao.transaction():
                user = await dao.find_by_id(ctx["user_id"])
            if user is None or not user.is_active:
                err = {"code": 401, "detail": "User not found or inactive"}
                await socket.send_json({"action": action, "error": err})
                await socket.close(code=4001, reason="User invalid")
                return
            ctx["user"] = user
            response = await _dispatch(action, auth, dao, ctx)
            await socket.send_json(response)

    except WebSocketDisconnect:
        pass
