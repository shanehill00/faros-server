"""Tests for agent command dispatch endpoints."""

from __future__ import annotations

import time

import pytest
from litestar.testing import TestClient

from tests.conftest import auth_headers, create_test_user

# --- helpers ---


async def _register_agent(
    client: TestClient,  # type: ignore[type-arg]
    agent_name: str = "cmd-bot",
) -> tuple[str, str, dict[str, str]]:
    """Register an agent and return (api_key, agent_id, jwt_headers)."""
    user = await create_test_user()
    headers = await auth_headers(user)

    start = client.post(
        "/api/agents/device/start",
        json={"agent_name": agent_name, "robot_type": "px4"},
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
    agent_id = poll.json()["agent_id"]
    return api_key, agent_id, headers


# --- Agent-facing: poll ---


@pytest.mark.asyncio
async def test_poll_commands_empty(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/commands returns empty list when no commands queued."""
    api_key, _, _ = await _register_agent(client)
    response = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_poll_commands_returns_pending(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/commands returns pending commands in poll format."""
    api_key, agent_id, headers = await _register_agent(client)

    # Queue a command via operator endpoint
    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "ModelDeploy", "payload": {"group": "drivetrain"}},
        headers=headers,
    )

    response = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    cmd = data[0]
    assert cmd["type"] == "ModelDeploy"
    assert cmd["payload"] == {"group": "drivetrain"}
    assert cmd["command_id"] == cmd["trace_id"]
    assert "command_id" in cmd


@pytest.mark.asyncio
async def test_poll_marks_in_progress(client: TestClient) -> None:  # type: ignore[type-arg]
    """Polling marks commands as in_progress; second poll returns empty."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop", "payload": None},
        headers=headers,
    )

    # First poll returns the command
    first = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert len(first.json()) == 1

    # Second poll returns empty (already in_progress)
    second = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert second.json() == []


@pytest.mark.asyncio
async def test_poll_commands_no_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/commands without auth returns 401."""
    response = client.get("/api/agents/commands")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_poll_commands_bad_key(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/commands with invalid key returns 401."""
    response = client.get(
        "/api/agents/commands",
        headers={"Authorization": "Bearer bad-key"},
    )
    assert response.status_code == 401


# --- Agent-facing: ack ---


@pytest.mark.asyncio
async def test_ack_command_stores_result(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/ack stores result and marks acked."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )

    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    response = client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True, "message": "stopped"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "acked"
    assert data["result"]["success"] is True


@pytest.mark.asyncio
async def test_ack_command_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/ack with unknown id returns 404."""
    api_key, _, _ = await _register_agent(client)

    response = client.post(
        "/api/agents/commands/nonexistent/ack",
        json={"success": False},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ack_command_wrong_agent(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/ack from wrong agent returns 404."""
    _, agent_id_a, headers_a = await _register_agent(client, "bot-a")
    api_key_b, _, _ = await _register_agent(client, "bot-b")

    # Queue command for agent A
    queued = client.post(
        f"/api/agents/{agent_id_a}/commands",
        json={"type": "Stop"},
        headers=headers_a,
    )
    command_id = queued.json()["id"]

    # Agent B tries to ack agent A's command
    response = client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": False},
        headers={"Authorization": f"Bearer {api_key_b}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ack_command_already_acked(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/ack twice returns 409."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )

    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    # First ack
    client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Second ack
    response = client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_ack_command_no_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/ack without auth returns 401."""
    response = client.post(
        "/api/agents/commands/some-id/ack",
        json={"success": True},
    )
    assert response.status_code == 401


# --- Operator-facing: queue ---


@pytest.mark.asyncio
async def test_queue_command(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands creates a pending command."""
    _, agent_id, headers = await _register_agent(client)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "ModelDeploy", "payload": {"url": "https://example.com"}},
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "ModelDeploy"
    assert data["payload"] == {"url": "https://example.com"}
    assert data["status"] == "pending"
    assert data["agent_id"] == agent_id
    assert data["result"] is None
    assert data["id"]


@pytest.mark.asyncio
async def test_queue_command_null_payload(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands with null payload succeeds."""
    _, agent_id, headers = await _register_agent(client)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["payload"] is None


@pytest.mark.asyncio
async def test_queue_command_missing_type(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands without type returns 400."""
    _, agent_id, headers = await _register_agent(client)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"payload": {}},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_queue_command_invalid_payload(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands with non-dict payload returns 400."""
    _, agent_id, headers = await _register_agent(client)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop", "payload": "not-a-dict"},
        headers=headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_queue_command_agent_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands for unknown agent returns 404."""
    user = await create_test_user()
    headers = await auth_headers(user)

    response = client.post(
        "/api/agents/nonexistent/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_queue_command_not_owner(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands by non-owner returns 401."""
    _, agent_id, _ = await _register_agent(client)

    # Create a different user
    other = await create_test_user(
        name="Other", provider_id="google-other", email="other@faros.dev",
    )
    other_headers = await auth_headers(other)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=other_headers,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_queue_command_no_auth(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands without JWT returns 401."""
    response = client.post(
        "/api/agents/some-id/commands",
        json={"type": "Stop"},
    )
    assert response.status_code == 401


# --- Operator-facing: list ---


@pytest.mark.asyncio
async def test_list_commands(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands returns all commands."""
    _, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "ModelDeploy", "payload": {"g": "d"}},
        headers=headers,
    )

    response = client.get(
        f"/api/agents/{agent_id}/commands",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["type"] == "Stop"
    assert data[1]["type"] == "ModelDeploy"


@pytest.mark.asyncio
async def test_list_commands_with_status_filter(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands?status=pending filters by status."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "A"},
        headers=headers,
    )
    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "B"},
        headers=headers,
    )

    # Poll to move commands to in_progress
    client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Queue another pending command
    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "C"},
        headers=headers,
    )

    # Filter by pending
    response = client.get(
        f"/api/agents/{agent_id}/commands",
        params={"status": "pending"},
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["type"] == "C"


@pytest.mark.asyncio
async def test_list_commands_empty(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands returns empty list when none."""
    _, agent_id, headers = await _register_agent(client)

    response = client.get(
        f"/api/agents/{agent_id}/commands",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_commands_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands for unknown agent returns 404."""
    user = await create_test_user()
    headers = await auth_headers(user)

    response = client.get(
        "/api/agents/nonexistent/commands",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_commands_not_owner(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands by non-owner returns 401."""
    _, agent_id, _ = await _register_agent(client)

    other = await create_test_user(
        name="Other2", provider_id="google-other2", email="other2@faros.dev",
    )
    other_headers = await auth_headers(other)

    response = client.get(
        f"/api/agents/{agent_id}/commands",
        headers=other_headers,
    )
    assert response.status_code == 401


# --- Operator-facing: get ---


@pytest.mark.asyncio
async def test_get_command(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands/{command_id} returns the command."""
    _, agent_id, headers = await _register_agent(client)

    queued = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    command_id = queued.json()["id"]

    response = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == command_id
    assert data["type"] == "Stop"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_get_command_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands/{command_id} for unknown returns 404."""
    _, agent_id, headers = await _register_agent(client)

    response = client.get(
        f"/api/agents/{agent_id}/commands/nonexistent",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_command_agent_not_found(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands/{command_id} for unknown agent returns 404."""
    user = await create_test_user()
    headers = await auth_headers(user)

    response = client.get(
        "/api/agents/nonexistent/commands/some-cmd",
        headers=headers,
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_command_not_owner(client: TestClient) -> None:  # type: ignore[type-arg]
    """GET /api/agents/{agent_id}/commands/{command_id} by non-owner returns 401."""
    _, agent_id, headers = await _register_agent(client)

    queued = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    command_id = queued.json()["id"]

    other = await create_test_user(
        name="Other3", provider_id="google-other3", email="other3@faros.dev",
    )
    other_headers = await auth_headers(other)

    response = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=other_headers,
    )
    assert response.status_code == 401


# --- Integration: full lifecycle ---


@pytest.mark.asyncio
async def test_full_lifecycle(client: TestClient) -> None:  # type: ignore[type-arg]
    """Queue -> poll -> ack -> get verifies full command lifecycle."""
    api_key, agent_id, headers = await _register_agent(client)

    # 1. Operator queues command
    queued = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "ModelDeploy", "payload": {"group": "drivetrain"}},
        headers=headers,
    )
    assert queued.status_code == 201
    command_id = queued.json()["id"]

    # 2. Agent polls and gets the command
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert poll.status_code == 200
    assert len(poll.json()) == 1
    assert poll.json()[0]["command_id"] == command_id

    # 3. Agent streams output while working
    for i in range(1, 4):
        out = client.post(
            f"/api/agents/commands/{command_id}/output",
            json={"output": f"step {i}\n"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
        assert out.status_code == 200

    # 4. Operator checks progress mid-flight
    mid = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert mid.json()["output"] == "step 1\nstep 2\nstep 3\n"
    assert mid.json()["status"] == "in_progress"

    # 5. Agent acks with result
    ack = client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True, "message": "deployed", "data": None},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acked"

    # 6. Operator gets the command and sees result + output
    detail = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    data = detail.json()
    assert data["status"] == "acked"
    assert data["result"]["success"] is True
    assert data["result"]["message"] == "deployed"
    assert data["output"] == "step 1\nstep 2\nstep 3\n"
    assert data["delivered_at"] is not None
    assert data["acked_at"] is not None


@pytest.mark.asyncio
async def test_multiple_commands_delivered_atomically(client: TestClient) -> None:  # type: ignore[type-arg]
    """Multiple pending commands are all delivered in a single poll."""
    api_key, agent_id, headers = await _register_agent(client)

    # Queue three commands
    for cmd_type in ["A", "B", "C"]:
        client.post(
            f"/api/agents/{agent_id}/commands",
            json={"type": cmd_type},
            headers=headers,
        )

    # Single poll returns all three
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert poll.status_code == 200
    types = [c["type"] for c in poll.json()]
    assert types == ["A", "B", "C"]

    # All are now in_progress
    listing = client.get(
        f"/api/agents/{agent_id}/commands",
        params={"status": "in_progress"},
        headers=headers,
    )
    assert len(listing.json()) == 3

    # Second poll returns empty
    second = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert second.json() == []


# --- Agent-facing: output append ---


@pytest.mark.asyncio
async def test_append_output_while_in_progress(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output succeeds when in_progress."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "DataCollect"},
        headers=headers,
    )
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    response = client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "Collecting bag 1/10...\n"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_append_output_accumulates(client: TestClient) -> None:  # type: ignore[type-arg]
    """Multiple appends concatenate output text."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "DataCollect"},
        headers=headers,
    )
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    for i in range(1, 4):
        client.post(
            f"/api/agents/commands/{command_id}/output",
            json={"output": f"line {i}\n"},
            headers={"Authorization": f"Bearer {api_key}"},
        )

    detail = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert detail.json()["output"] == "line 1\nline 2\nline 3\n"


@pytest.mark.asyncio
async def test_append_output_visible_in_get(client: TestClient) -> None:  # type: ignore[type-arg]
    """Output field appears in operator GET command response."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "DataCollect"},
        headers=headers,
    )
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "progress update"},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    detail = client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert detail.json()["output"] == "progress update"


@pytest.mark.asyncio
async def test_append_output_pending_returns_409(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output on pending command returns 409."""
    api_key, agent_id, headers = await _register_agent(client)

    queued = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    command_id = queued.json()["id"]

    response = client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "text"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_append_output_acked_returns_409(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output on acked command returns 409."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    command_id = poll.json()[0]["command_id"]

    client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True},
        headers={"Authorization": f"Bearer {api_key}"},
    )

    response = client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "too late"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_append_output_nonexistent_returns_404(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output for unknown command returns 404."""
    api_key, _, _ = await _register_agent(client)

    response = client.post(
        "/api/agents/commands/nonexistent/output",
        json={"output": "text"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_append_output_wrong_agent_returns_404(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output from wrong agent returns 404."""
    _, agent_id_a, headers_a = await _register_agent(client, "bot-a")
    api_key_b, _, _ = await _register_agent(client, "bot-b")

    queued = client.post(
        f"/api/agents/{agent_id_a}/commands",
        json={"type": "Stop"},
        headers=headers_a,
    )
    command_id = queued.json()["id"]

    response = client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "text"},
        headers={"Authorization": f"Bearer {api_key_b}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_append_output_no_auth_returns_401(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output without auth returns 401."""
    response = client.post(
        "/api/agents/commands/some-id/output",
        json={"output": "text"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_append_output_empty_string_returns_400(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output with empty output returns 400."""
    api_key, _, _ = await _register_agent(client)

    response = client.post(
        "/api/agents/commands/some-id/output",
        json={"output": ""},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_append_output_missing_field_returns_400(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/commands/{id}/output without output field returns 400."""
    api_key, _, _ = await _register_agent(client)

    response = client.post(
        "/api/agents/commands/some-id/output",
        json={"text": "wrong field"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_queue_command_empty_type_rejected(client: TestClient) -> None:  # type: ignore[type-arg]
    """POST /api/agents/{agent_id}/commands with empty type string returns 400."""
    _, agent_id, headers = await _register_agent(client)

    response = client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "  "},
        headers=headers,
    )
    assert response.status_code == 400


# --- Command TTL / expiry ---


@pytest.mark.asyncio
async def test_poll_fresh_command_delivered(client: TestClient) -> None:  # type: ignore[type-arg]
    """A command within TTL is delivered normally (default TTL=30s)."""
    api_key, agent_id, headers = await _register_agent(client)

    client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert poll.status_code == 200
    assert len(poll.json()) == 1
    assert poll.json()[0]["type"] == "Stop"


@pytest.mark.asyncio
async def test_poll_stale_command_expired(
    ttl0_client: TestClient,  # type: ignore[type-arg]
) -> None:
    """A command older than TTL is marked expired and not delivered."""
    api_key, agent_id, headers = await _register_agent(ttl0_client)

    ttl0_client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )

    # TTL=0 means any age > 0 is expired; tiny sleep ensures created_at is in the past
    time.sleep(0.01)

    poll = ttl0_client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert poll.status_code == 200
    assert poll.json() == []

    # Operator sees the command as expired
    listing = ttl0_client.get(
        f"/api/agents/{agent_id}/commands",
        params={"status": "expired"},
        headers=headers,
    )
    assert len(listing.json()) == 1
    assert listing.json()[0]["status"] == "expired"
    assert listing.json()[0]["delivered_at"] is not None


@pytest.mark.asyncio
async def test_poll_mixed_fresh_and_stale(client: TestClient) -> None:  # type: ignore[type-arg]
    """With default TTL=30s, all commands are fresh and delivered."""
    api_key, agent_id, headers = await _register_agent(client)

    for cmd_type in ["A", "B", "C"]:
        client.post(
            f"/api/agents/{agent_id}/commands",
            json={"type": cmd_type},
            headers=headers,
        )

    poll = client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    types = [c["type"] for c in poll.json()]
    assert types == ["A", "B", "C"]


@pytest.mark.asyncio
async def test_expired_command_visible_in_get(
    ttl0_client: TestClient,  # type: ignore[type-arg]
) -> None:
    """Expired commands are visible to the operator via GET with status=expired."""
    api_key, agent_id, headers = await _register_agent(ttl0_client)

    queued = ttl0_client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "ModelDeploy", "payload": {"group": "drivetrain"}},
        headers=headers,
    )
    command_id = queued.json()["id"]

    time.sleep(0.01)

    # Agent polls — command is expired, not delivered
    ttl0_client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Operator gets the specific command
    detail = ttl0_client.get(
        f"/api/agents/{agent_id}/commands/{command_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["status"] == "expired"
    assert detail.json()["delivered_at"] is not None


@pytest.mark.asyncio
async def test_ack_expired_command_returns_409(
    ttl0_client: TestClient,  # type: ignore[type-arg]
) -> None:
    """POST /api/agents/commands/{id}/ack on expired command returns 409."""
    api_key, agent_id, headers = await _register_agent(ttl0_client)

    queued = ttl0_client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    command_id = queued.json()["id"]

    time.sleep(0.01)

    # Poll to trigger expiry
    ttl0_client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Try to ack the expired command
    response = ttl0_client.post(
        f"/api/agents/commands/{command_id}/ack",
        json={"success": True},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_append_output_expired_returns_409(
    ttl0_client: TestClient,  # type: ignore[type-arg]
) -> None:
    """POST /api/agents/commands/{id}/output on expired command returns 409."""
    api_key, agent_id, headers = await _register_agent(ttl0_client)

    queued = ttl0_client.post(
        f"/api/agents/{agent_id}/commands",
        json={"type": "Stop"},
        headers=headers,
    )
    command_id = queued.json()["id"]

    time.sleep(0.01)

    # Poll to trigger expiry
    ttl0_client.get(
        "/api/agents/commands",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    # Try to append output to the expired command
    response = ttl0_client.post(
        f"/api/agents/commands/{command_id}/output",
        json={"output": "too late"},
        headers={"Authorization": f"Bearer {api_key}"},
    )
    assert response.status_code == 409
