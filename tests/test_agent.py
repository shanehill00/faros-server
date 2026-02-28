"""Tests for agent registration and device flow endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from litestar.testing import TestClient

from faros_server.utils.db import Database
from faros_server.utils.jwt import JWTManager
from faros_server.utils.time import Time
from tests.conftest import auth_headers, create_test_user


def _oauth_client(client: TestClient) -> object:  # type: ignore[type-arg]
    """Return the GoogleOAuthClient inside the AuthResource."""
    return client.app.state.auth._oauth_client

# --- Device flow: start ---


def test_start_device_flow(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/device/start returns device_code, user_code, verification_url."""
    response = client.post(
        "/api/agents/device/start",
        json={"agent_name": "turtlebot3-lab1", "robot_type": "turtlebot3"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "device_code" in data
    assert "user_code" in data
    assert "-" in data["user_code"]
    assert len(data["user_code"]) == 9  # XXXX-XXXX
    assert "verification_url" in data
    assert data["user_code"] in data["verification_url"]
    assert data["expires_in"] == 900  # 15 min
    assert data["interval"] == 5


def test_start_device_flow_missing_fields(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/device/start without required fields returns 400."""
    response = client.post(
        "/api/agents/device/start",
        json={"agent_name": ""},
    )
    assert response.status_code == 400


# --- Device flow: poll ---


def test_poll_pending(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling before approval returns authorization_pending."""
    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "bot1", "robot_type": "px4"},
    )
    device_code = start.json()["device_code"]
    response = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "authorization_pending"


def test_poll_unknown_device_code(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling with unknown device_code returns 404."""
    response = client.post(
        "/api/agents/device/poll",
        json={"device_code": "nonexistent"},
    )
    assert response.status_code == 404


def test_poll_missing_device_code(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling without device_code returns 400."""
    response = client.post(
        "/api/agents/device/poll",
        json={"device_code": ""},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_poll_expired(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling an expired registration returns expired status."""
    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "expired-bot", "robot_type": "px4"},
    )
    device_code = start.json()["device_code"]

    # Manually expire the registration
    from sqlalchemy import update as sa_update

    from faros_server.models.agent import DeviceRegistration

    pool = Database.get_pool()
    async with pool() as session:
        await session.execute(
            sa_update(DeviceRegistration)
            .where(DeviceRegistration.device_code == device_code)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()

    response = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "expired"


# --- Device flow: approve ---


@pytest.mark.asyncio
async def test_approve_device(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approving a device creates agent and API key, poll returns complete."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "lab-bot-1", "robot_type": "turtlebot3"},
    )
    user_code = start.json()["user_code"]
    device_code = start.json()["device_code"]

    # Approve
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["agent_name"] == "lab-bot-1"
    assert "agent_id" in data

    # Poll should now return complete with api_key
    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    assert poll.json()["status"] == "complete"
    assert poll.json()["api_key"].startswith("fk_")
    assert poll.json()["agent_id"] == data["agent_id"]


@pytest.mark.asyncio
async def test_approve_unknown_user_code(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approving with unknown user_code returns 404."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": "ZZZZ-9999"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_approve_expired_device(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approving an expired device returns 410."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "expired-approve", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    from sqlalchemy import update as sa_update

    from faros_server.models.agent import DeviceRegistration

    pool = Database.get_pool()
    async with pool() as session:
        await session.execute(
            sa_update(DeviceRegistration)
            .where(DeviceRegistration.user_code == user_code)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()

    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )
    assert response.status_code == 410


@pytest.mark.asyncio
async def test_approve_already_used(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approving a device twice returns 409."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "double-approve", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    # First approve succeeds
    client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )

    # Second approve returns 409
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )
    assert response.status_code == 409


def test_approve_requires_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approve endpoint requires JWT auth."""
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": "ABCD-1234"},
    )
    assert response.status_code == 401


# --- Device page (HTML approval) ---


@pytest.mark.asyncio
async def test_device_page_returns_html(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/device/{user_code}?token=JWT returns HTML approval page."""
    user = await create_test_user()
    token = JWTManager.create_token({"sub": user.id})

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "page-bot", "robot_type": "turtlebot3"},
    )
    user_code = start.json()["user_code"]

    response = client.get(
        f"/api/agents/device/{user_code}?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "page-bot" in body
    assert "turtlebot3" in body
    assert "Approve" in body


@pytest.mark.asyncio
async def test_device_page_unauthenticated_redirects(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/device/{code} without token redirects to Google SSO."""
    _oauth_client(client)._client_id = "test-client-id"
    response = client.get(
        "/api/agents/device/ABCD-1234",
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert "accounts.google.com" in location
    assert "test-client-id" in location


@pytest.mark.asyncio
async def test_device_page_auth_header(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/device/{code} with Authorization header works."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "header-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    response = client.get(
        f"/api/agents/device/{user_code}",
        headers=headers,
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "header-bot" in response.text


@pytest.mark.asyncio
async def test_device_page_unknown_code_html(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/device/{code} with unknown code returns 404 HTML."""
    user = await create_test_user()
    token = JWTManager.create_token({"sub": user.id})
    response = client.get(
        f"/api/agents/device/ZZZZ-0000?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert "Unknown device code" in response.text


@pytest.mark.asyncio
async def test_device_page_already_approved(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page for already-approved registration shows 'already registered'."""
    user = await create_test_user()
    headers = await auth_headers(user)
    token = JWTManager.create_token({"sub": user.id})

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "approved-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    # Approve first
    client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )

    response = client.get(
        f"/api/agents/device/{user_code}?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "Already Registered" in response.text


@pytest.mark.asyncio
async def test_device_page_cookie_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/device/{code} with faros_token cookie works without ?token= param."""
    user = await create_test_user()
    token = JWTManager.create_token({"sub": user.id})

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "cookie-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    response = client.get(
        f"/api/agents/device/{user_code}",
        cookies={"faros_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "cookie-bot" in response.text


def test_device_page_token_no_sub_redirects(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page with token missing 'sub' claim redirects to SSO."""
    _oauth_client(client)._client_id = "test-client-id"
    token = JWTManager.create_token({"foo": "bar"})
    response = client.get(
        f"/api/agents/device/ABCD-1234?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]


@pytest.mark.asyncio
async def test_device_page_token_deleted_user_redirects(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page with token for nonexistent user redirects to SSO."""
    _oauth_client(client)._client_id = "test-client-id"
    token = JWTManager.create_token({"sub": "nonexistent-id-000"})
    response = client.get(
        f"/api/agents/device/ABCD-1234?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]


def test_device_page_bad_token_redirects(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page with invalid token redirects to SSO (treats as unauthenticated)."""
    _oauth_client(client)._client_id = "test-client-id"
    response = client.get(
        "/api/agents/device/ABCD-1234?token=invalid.jwt.token",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "accounts.google.com" in response.headers["location"]


def test_device_page_oauth_not_configured(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page returns 500 HTML when OAuth is not configured."""
    # Default test config has empty client_id → not configured
    response = client.get(
        "/api/agents/device/ABCD-1234",
        follow_redirects=False,
    )
    assert response.status_code == 500
    assert "text/html" in response.headers["content-type"]
    assert "OAuth not configured" in response.text


# --- List agents ---


@pytest.mark.asyncio
async def test_list_agents_empty(client: TestClient) -> None:  # type: ignore[type-arg]
    """List agents returns empty list when user has no agents."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response = client.get("/api/agents/", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_agents_after_registration(client: TestClient) -> None:  # type: ignore[type-arg]
    """List agents returns the registered agent."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "list-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )

    response = client.get("/api/agents/", headers=headers)
    assert response.status_code == 200
    agents = response.json()
    assert len(agents) == 1
    assert agents[0]["name"] == "list-bot"
    assert agents[0]["robot_type"] == "px4"


def test_list_agents_requires_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """List agents requires JWT auth."""
    response = client.get("/api/agents/")
    assert response.status_code == 401


# --- Revoke key ---


@pytest.mark.asyncio
async def test_revoke_key(client: TestClient) -> None:  # type: ignore[type-arg]
    """Revoking an agent's key returns revoked count."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "revoke-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    approve_data = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    ).json()
    agent_id = approve_data["agent_id"]

    response = client.delete(
        f"/api/agents/{agent_id}/key", headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["revoked"] == 1

    # Second revoke returns 0 (already revoked)
    response2 = client.delete(
        f"/api/agents/{agent_id}/key", headers=headers,
    )
    assert response2.json()["revoked"] == 0


@pytest.mark.asyncio
async def test_revoke_key_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """Revoking a nonexistent agent's key returns 404."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response = client.delete(
        "/api/agents/nonexistent-id/key", headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_key_not_owner(client: TestClient) -> None:  # type: ignore[type-arg]
    """Revoking another user's agent key returns 401."""
    owner = await create_test_user(
        name="Owner", provider_id="g-owner", email="owner@faros.dev",
    )
    owner_headers = await auth_headers(owner)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "other-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    approve_data = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=owner_headers,
    ).json()
    agent_id = approve_data["agent_id"]

    # Different user tries to revoke
    other = await create_test_user(
        name="Other", provider_id="g-other", email="other@faros.dev",
    )
    other_headers = await auth_headers(other)
    response = client.delete(
        f"/api/agents/{agent_id}/key", headers=other_headers,
    )
    assert response.status_code == 401


def test_revoke_key_requires_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """Revoke key requires JWT auth."""
    response = client.delete("/api/agents/some-id/key")
    assert response.status_code == 401


# --- Approve: missing user_code ---


@pytest.mark.asyncio
async def test_approve_missing_user_code(client: TestClient) -> None:  # type: ignore[type-arg]
    """Approve without user_code returns 400."""
    user = await create_test_user()
    headers = await auth_headers(user)
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": ""},
        headers=headers,
    )
    assert response.status_code == 400


# --- Device page: expired ---


@pytest.mark.asyncio
async def test_device_page_expired_html(client: TestClient) -> None:  # type: ignore[type-arg]
    """Device page for expired registration returns 410 HTML."""
    user = await create_test_user()
    token = JWTManager.create_token({"sub": user.id})

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "expired-page", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]

    from sqlalchemy import update as sa_update

    from faros_server.models.agent import DeviceRegistration

    pool = Database.get_pool()
    async with pool() as session:
        await session.execute(
            sa_update(DeviceRegistration)
            .where(DeviceRegistration.user_code == user_code)
            .values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await session.commit()

    response = client.get(
        f"/api/agents/device/{user_code}?token={token}",
        follow_redirects=False,
    )
    assert response.status_code == 410
    assert "text/html" in response.headers["content-type"]
    assert "expired" in response.text.lower()


# --- Agent reuse: same name approved twice ---


@pytest.mark.asyncio
async def test_returning_agent_requires_approval(client: TestClient) -> None:  # type: ignore[type-arg]
    """A second device/start for an existing agent still requires browser approval."""
    user = await create_test_user()
    headers = await auth_headers(user)

    # First registration — manual approval
    start1 = client.post(
        "/api/agents/device/start",
        json={"agent_name": "reuse-bot", "robot_type": "px4"},
    )
    response1 = client.post(
        "/api/agents/device/approve",
        json={"user_code": start1.json()["user_code"]},
        headers=headers,
    )
    agent_id_1 = response1.json()["agent_id"]

    # Second registration — still pending, requires browser approval
    start2 = client.post(
        "/api/agents/device/start",
        json={"agent_name": "reuse-bot", "robot_type": "px4"},
    )
    poll2 = client.post(
        "/api/agents/device/poll",
        json={"device_code": start2.json()["device_code"]},
    )
    assert poll2.json()["status"] == "authorization_pending"

    # Manual approval reuses the same agent
    response2 = client.post(
        "/api/agents/device/approve",
        json={"user_code": start2.json()["user_code"]},
        headers=headers,
    )
    assert response2.json()["agent_id"] == agent_id_1


@pytest.mark.asyncio
async def test_approve_reuses_agent_without_owner(client: TestClient) -> None:  # type: ignore[type-arg]
    """approve_device reuses an existing agent that has no owner (empty owner_id)."""
    from faros_server.models.agent import Agent

    user = await create_test_user()
    headers = await auth_headers(user)

    # Create an agent directly with empty owner_id (no auto-approve at start)
    pool = Database.get_pool()
    async with pool() as session:
        agent = Agent(name="orphan-bot", robot_type="px4", owner_id="")
        session.add(agent)
        await session.commit()
        await session.refresh(agent)
        orphan_id = agent.id

    # Start device flow — no auto-approve because owner_id is empty
    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "orphan-bot", "robot_type": "px4"},
    )
    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": start.json()["device_code"]},
    )
    assert poll.json()["status"] == "authorization_pending"

    # Manual approval reuses the existing agent
    response = client.post(
        "/api/agents/device/approve",
        json={"user_code": start.json()["user_code"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["agent_id"] == orphan_id


# --- resolve_api_key (service-level test) ---


@pytest.mark.asyncio
async def test_resolve_api_key(client: TestClient) -> None:  # type: ignore[type-arg]
    """resolve_api_key returns the correct agent for a valid key."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "resolve-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    device_code = start.json()["device_code"]

    client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )

    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    api_key = poll.json()["api_key"]

    # Resolve through service
    agent_service = client.app.state.agent._service
    agent = await agent_service.resolve_api_key(api_key)
    assert agent.name == "resolve-bot"


@pytest.mark.asyncio
async def test_resolve_api_key_invalid(client: TestClient) -> None:  # type: ignore[type-arg]
    """resolve_api_key raises ValueError for invalid key."""
    agent_service = client.app.state.agent._service
    with pytest.raises(ValueError, match="Invalid API key"):
        await agent_service.resolve_api_key("fk_bogus_key_value")


@pytest.mark.asyncio
async def test_resolve_api_key_revoked(client: TestClient) -> None:  # type: ignore[type-arg]
    """resolve_api_key raises ValueError for a revoked key."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "revoked-resolve", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    device_code = start.json()["device_code"]

    approve_data = client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    ).json()

    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    api_key = poll.json()["api_key"]

    # Revoke the key
    client.delete(
        f"/api/agents/{approve_data['agent_id']}/key", headers=headers,
    )

    # Now resolve should fail
    agent_service = client.app.state.agent._service
    with pytest.raises(ValueError, match="Invalid API key"):
        await agent_service.resolve_api_key(api_key)


# --- Agent logout (API-key auth) ---


@pytest.mark.asyncio
async def test_agent_logout_revokes_keys(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/logout revokes the calling agent's keys."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "logout-bot", "robot_type": "px4"},
    )
    client.post(
        "/api/agents/device/approve",
        json={"user_code": start.json()["user_code"]},
        headers=headers,
    )
    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": start.json()["device_code"]},
    )
    api_key = poll.json()["api_key"]

    response = client.post(
        "/api/agents/logout",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json()["revoked"] >= 1

    # Key is now invalid
    agent_service = client.app.state.agent._service
    with pytest.raises(ValueError, match="Invalid API key"):
        await agent_service.resolve_api_key(api_key)


def test_agent_logout_invalid_key(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/logout with invalid key returns 401."""
    response = client.post(
        "/api/agents/logout",
        headers={"Authorization": "Bearer fk_bogus"},
    )
    assert response.status_code == 401


def test_agent_logout_no_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/logout without auth returns 401."""
    response = client.post("/api/agents/logout")
    assert response.status_code == 401


# --- Time.ensure_utc unit tests ---


def test_ensure_utc_naive() -> None:
    """Time.ensure_utc adds UTC to naive datetimes."""
    naive = datetime(2026, 1, 1, 12, 0, 0)
    result = Time.ensure_utc(naive)
    assert result.tzinfo is timezone.utc


def test_ensure_utc_aware() -> None:
    """Time.ensure_utc passes through tz-aware datetimes unchanged."""
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    result = Time.ensure_utc(aware)
    assert result is aware


# --- poll fallback status ---


@pytest.mark.asyncio
async def test_poll_unknown_status(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling a registration with unexpected status returns that status."""
    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "odd-status", "robot_type": "px4"},
    )
    device_code = start.json()["device_code"]

    # Manually set an unexpected status
    from sqlalchemy import update as sa_update

    from faros_server.models.agent import DeviceRegistration

    pool = Database.get_pool()
    async with pool() as session:
        await session.execute(
            sa_update(DeviceRegistration)
            .where(DeviceRegistration.device_code == device_code)
            .values(status="rejected")
        )
        await session.commit()

    response = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


# --- resolve_api_key with orphaned key ---


@pytest.mark.asyncio
async def test_resolve_api_key_orphaned_agent(client: TestClient) -> None:  # type: ignore[type-arg]
    """resolve_api_key raises ValueError when agent row is missing."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": "orphan-bot", "robot_type": "px4"},
    )
    user_code = start.json()["user_code"]
    device_code = start.json()["device_code"]

    client.post(
        "/api/agents/device/approve",
        json={"user_code": user_code},
        headers=headers,
    )

    poll = client.post(
        "/api/agents/device/poll",
        json={"device_code": device_code},
    )
    api_key = poll.json()["api_key"]

    # Delete the agent row directly
    from sqlalchemy import delete as sa_delete

    from faros_server.models.agent import Agent

    pool = Database.get_pool()
    async with pool() as session:
        await session.execute(
            sa_delete(Agent).where(Agent.name == "orphan-bot")
        )
        await session.commit()

    agent_service = client.app.state.agent._service
    with pytest.raises(ValueError, match="Agent not found for API key"):
        await agent_service.resolve_api_key(api_key)
