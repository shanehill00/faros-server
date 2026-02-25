"""Tests for WebSocket transport."""

from __future__ import annotations

import pytest
from litestar.testing import TestClient

from faros_server.app import create_app
from faros_server.config import Settings
from faros_server.utils.db import get_pool
from faros_server.utils.jwt import JWTManager
from tests.conftest import create_test_user

_test_jwt = JWTManager(secret_key="test-secret-key", expire_minutes=30)


@pytest.fixture()
def ws_settings() -> Settings:
    """Test settings for WebSocket tests."""
    return Settings(
        secret_key="test-secret-key",
        database_url="sqlite+aiosqlite://",
        token_expire_minutes=30,
    )


@pytest.fixture()
def ws_client(ws_settings: Settings) -> TestClient:  # type: ignore[type-arg]
    """Test client for WebSocket tests — lifespan handles init_db/create_tables."""
    app = create_app(ws_settings)
    with TestClient(app=app) as tc:
        yield tc  # type: ignore[misc]


@pytest.mark.asyncio
async def test_ws_auth_and_me(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: authenticate then call auth.me."""
    user = await create_test_user()
    token = _test_jwt.create_token({"sub": user.id})

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["action"] == "auth.me"
        assert resp["data"]["name"] == "Test User"
        assert len(resp["data"]["auth_methods"]) == 1


@pytest.mark.asyncio
async def test_ws_auth_only(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: authenticate without an action returns ok."""
    user = await create_test_user()
    token = _test_jwt.create_token({"sub": user.id})

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"token": token})
        resp = ws.receive_json()
        assert resp["action"] == "auth"
        assert resp["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_ws_no_token(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: first message without token returns 401."""
    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
        assert resp["error"]["detail"] == "Token required"


@pytest.mark.asyncio
async def test_ws_bad_token(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: invalid token closes connection."""
    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": "bad.token.here"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401


@pytest.mark.asyncio
async def test_ws_unknown_action(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: unknown action returns 400."""
    user = await create_test_user()
    token = _test_jwt.create_token({"sub": user.id})

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "bogus.action", "token": token})
        resp = ws.receive_json()
        assert resp["action"] == "bogus.action"
        assert resp["error"]["code"] == 400


@pytest.mark.asyncio
async def test_ws_multiple_actions(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: authenticate once, send multiple actions on same connection."""
    user = await create_test_user()
    token = _test_jwt.create_token({"sub": user.id})

    with ws_client.websocket_connect("/ws") as ws:
        # Auth first
        ws.send_json({"token": token})
        resp = ws.receive_json()
        assert resp["data"]["status"] == "ok"

        # Then call me twice
        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["data"]["name"] == "Test User"

        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["data"]["name"] == "Test User"


@pytest.mark.asyncio
async def test_ws_token_no_sub(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: token without sub claim is rejected."""
    token = _test_jwt.create_token({"foo": "bar"})

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401


@pytest.mark.asyncio
async def test_ws_user_deactivated_mid_session(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: user deactivated after auth gets rejected on next action."""
    from sqlalchemy import select

    from faros_server.models.user import User

    user = await create_test_user(email="ws-deact@faros.dev", provider_id="g-ws-deact")
    token = _test_jwt.create_token({"sub": user.id})

    with ws_client.websocket_connect("/ws") as ws:
        # Authenticate successfully
        ws.send_json({"token": token})
        resp = ws.receive_json()
        assert resp["data"]["status"] == "ok"

        # Deactivate user mid-session
        async with get_pool()() as db:
            result = await db.execute(select(User).where(User.id == user.id))
            db_user = result.scalar_one()
            db_user.is_active = False
            await db.commit()

        # Next action should fail
        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401


@pytest.mark.asyncio
async def test_ws_inactive_user(ws_client: TestClient) -> None:  # type: ignore[type-arg]
    """WebSocket: inactive user is rejected at authentication."""
    from sqlalchemy import select

    from faros_server.models.user import User

    user = await create_test_user(email="ws-inactive@faros.dev", provider_id="g-ws-inact")
    token = _test_jwt.create_token({"sub": user.id})

    # Deactivate after token is created
    async with get_pool()() as db:
        result = await db.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()
        db_user.is_active = False
        await db.commit()

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
        assert resp["error"]["detail"] == "Invalid token"
