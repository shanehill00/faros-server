"""WebSocket transport — same service layer, different protocol."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from faros_server.auth.jwt import decode_token
from faros_server.dao.user_dao import UserDAO
from faros_server.db import get_session
from faros_server.services.user_service import UserService

router = APIRouter()


async def _authenticate(
    token: str, secret_key: str, dao: UserDAO
) -> dict[str, Any] | None:
    """Validate a JWT token and return user, or None on failure."""
    try:
        payload = decode_token(token, secret_key)
    except ValueError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    user = await dao.find_by_id(user_id)
    if user is None or not user.is_active:
        return None
    return {"user_id": user.id, "user": user}


async def _dispatch(
    action: str,
    data: dict[str, Any],
    svc: UserService,
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Route an action to the appropriate service method."""
    if action == "auth.me":
        result = await svc.load_user_response(ctx["user"])
        return {"action": action, "data": result}

    return {"action": action, "error": {"code": 400, "detail": f"Unknown action: {action}"}}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """Handle WebSocket connections with JSON message dispatch."""
    await websocket.accept()

    settings = websocket.app.state.settings
    ctx: dict[str, Any] | None = None

    try:
        while True:
            msg = await websocket.receive_json()
            action: str = msg.get("action", "")

            # First message must authenticate
            if ctx is None:
                token = msg.get("token", "")
                if not token:
                    await websocket.send_json(
                        {"action": action, "error": {"code": 401, "detail": "Token required"}}
                    )
                    continue

                async for session in get_session():
                    dao = UserDAO(session)
                    ctx = await _authenticate(token, settings.secret_key, dao)

                if ctx is None:
                    await websocket.send_json(
                        {"action": action, "error": {"code": 401, "detail": "Invalid token"}}
                    )
                    await websocket.close(code=4001, reason="Authentication failed")
                    return

                # If the auth message also has an action, process it
                if not action:
                    await websocket.send_json({"action": "auth", "data": {"status": "ok"}})
                    continue

            # Authenticated — dispatch action
            async for session in get_session():
                dao = UserDAO(session)
                svc = UserService(dao)
                # Refresh user from DB for each action
                user = await dao.find_by_id(ctx["user_id"])
                if user is None or not user.is_active:
                    err = {"code": 401, "detail": "User not found or inactive"}
                    await websocket.send_json({"action": action, "error": err})
                    await websocket.close(code=4001, reason="User invalid")
                    return
                ctx["user"] = user
                response = await _dispatch(action, msg.get("data", {}), svc, ctx)
                await websocket.send_json(response)

    except WebSocketDisconnect:
        pass
