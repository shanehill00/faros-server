"""Tests for WebSocket transport."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from faros_server.app import create_app
from faros_server.auth.jwt import create_token
from faros_server.config import Settings
from faros_server.db import close_db, create_tables, init_db
from tests.conftest import create_test_user


@pytest.fixture()
def ws_settings() -> Settings:
    """Test settings for WebSocket tests."""
    return Settings(
        secret_key="test-secret-key",
        database_url="sqlite+aiosqlite://",
        token_expire_minutes=30,
    )


@pytest.mark.asyncio
async def test_ws_auth_and_me(ws_settings: Settings) -> None:
    """WebSocket: authenticate then call auth.me."""
    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user()
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["action"] == "auth.me"
        assert resp["data"]["name"] == "Test User"
        assert len(resp["data"]["auth_methods"]) == 1
    await close_db()


@pytest.mark.asyncio
async def test_ws_auth_only(ws_settings: Settings) -> None:
    """WebSocket: authenticate without an action returns ok."""
    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user()
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"token": token})
        resp = ws.receive_json()
        assert resp["action"] == "auth"
        assert resp["data"]["status"] == "ok"
    await close_db()


@pytest.mark.asyncio
async def test_ws_no_token(ws_settings: Settings) -> None:
    """WebSocket: first message without token returns 401."""
    init_db(ws_settings.database_url)
    await create_tables()

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
        assert resp["error"]["detail"] == "Token required"
    await close_db()


@pytest.mark.asyncio
async def test_ws_bad_token(ws_settings: Settings) -> None:
    """WebSocket: invalid token closes connection."""
    init_db(ws_settings.database_url)
    await create_tables()

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": "bad.token.here"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401


@pytest.mark.asyncio
async def test_ws_unknown_action(ws_settings: Settings) -> None:
    """WebSocket: unknown action returns 400."""
    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user()
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "bogus.action", "token": token})
        resp = ws.receive_json()
        assert resp["action"] == "bogus.action"
        assert resp["error"]["code"] == 400


@pytest.mark.asyncio
async def test_ws_multiple_actions(ws_settings: Settings) -> None:
    """WebSocket: authenticate once, send multiple actions on same connection."""
    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user()
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
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
    await close_db()


@pytest.mark.asyncio
async def test_ws_token_no_sub(ws_settings: Settings) -> None:
    """WebSocket: token without sub claim is rejected."""
    init_db(ws_settings.database_url)
    await create_tables()
    token = create_token({"foo": "bar"}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
    await close_db()


@pytest.mark.asyncio
async def test_ws_user_deactivated_mid_session(ws_settings: Settings) -> None:
    """WebSocket: user deactivated after auth gets rejected on next action."""
    from sqlalchemy import select

    from faros_server.db import get_session
    from faros_server.models.user import User

    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user(email="ws-deact@faros.dev", provider_id="g-ws-deact")
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        # Authenticate successfully
        ws.send_json({"token": token})
        resp = ws.receive_json()
        assert resp["data"]["status"] == "ok"

        # Deactivate user mid-session
        async for session in get_session():
            result = await session.execute(select(User).where(User.id == user.id))
            db_user = result.scalar_one()
            db_user.is_active = False
            await session.commit()

        # Next action should fail
        ws.send_json({"action": "auth.me"})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
    await close_db()


@pytest.mark.asyncio
async def test_ws_inactive_user(ws_settings: Settings) -> None:
    """WebSocket: inactive user is rejected at authentication."""
    from sqlalchemy import select

    from faros_server.db import get_session
    from faros_server.models.user import User

    init_db(ws_settings.database_url)
    await create_tables()
    user = await create_test_user(email="ws-inactive@faros.dev", provider_id="g-ws-inact")
    token = create_token({"sub": user.id}, ws_settings.secret_key)

    # Deactivate after token is created
    async for session in get_session():
        result = await session.execute(select(User).where(User.id == user.id))
        db_user = result.scalar_one()
        db_user.is_active = False
        await session.commit()

    app = create_app(ws_settings)
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "auth.me", "token": token})
        resp = ws.receive_json()
        assert resp["error"]["code"] == 401
        assert resp["error"]["detail"] == "Invalid token"
    await close_db()
