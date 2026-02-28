"""Business logic for agent registration and device flow."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from faros_server.dao.agent_dao import AgentDAO
from faros_server.models.agent import Agent, DeviceRegistration
from faros_server.utils.crypto import Crypto
from faros_server.utils.time import Time


class AgentService:
    """Built once at startup with its DAO pre-wired.

    Each method wraps its DAO calls in a transaction — one unit of work
    per service call.
    """

    def __init__(
        self, agent_dao: AgentDAO, *, expire_minutes: int = 15,
    ) -> None:
        self._dao = agent_dao
        self._expire_minutes = expire_minutes

    async def start_device_flow(
        self, agent_name: str, robot_type: str,
    ) -> dict[str, str | int]:
        """Initiate device-flow registration.

        Always creates a pending registration that requires browser approval.

        Returns:
            Dict with device_code, user_code, expires_in, and interval.
        """
        device_code = secrets.token_urlsafe(32)
        user_code = Crypto.generate_user_code()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self._expire_minutes,
        )

        async with self._dao.transaction():
            await self._dao.create_device_registration(
                device_code=device_code,
                user_code=user_code,
                agent_name=agent_name,
                robot_type=robot_type,
                expires_at=expires_at,
            )
            await self._dao.commit()

        return {
            "device_code": device_code,
            "user_code": user_code,
            "expires_in": self._expire_minutes * 60,
            "interval": 5,
        }

    async def poll_device_flow(
        self, device_code: str,
    ) -> dict[str, str]:
        """Poll for device-flow completion.

        Returns:
            Dict with status. If approved, includes api_key and agent_id.

        Raises:
            ValueError: If device_code is unknown.
        """
        async with self._dao.transaction():
            reg = await self._dao.find_registration_by_device_code(device_code)

        if reg is None:
            raise ValueError("Unknown device code")

        now = datetime.now(timezone.utc)
        if now > Time.ensure_utc(reg.expires_at):
            return {"status": "expired"}

        if reg.status == "pending":
            return {"status": "authorization_pending"}

        if reg.status == "approved" and reg.api_key_plaintext and reg.agent_id:
            return {
                "status": "complete",
                "api_key": reg.api_key_plaintext,
                "agent_id": reg.agent_id,
            }

        return {"status": reg.status}

    async def approve_device(
        self, user_code: str, owner_id: str,
    ) -> dict[str, str]:
        """Approve a pending device registration.

        Creates the Agent and ApiKey, updates the DeviceRegistration.

        Returns:
            Dict with agent_id and agent_name.

        Raises:
            ValueError: If user_code is unknown, expired, or already used.
        """
        async with self._dao.transaction():
            reg = await self._dao.find_registration_by_user_code(user_code)

            if reg is None:
                raise ValueError("Unknown user code")

            now = datetime.now(timezone.utc)
            if now > Time.ensure_utc(reg.expires_at):
                raise ValueError("Device code has expired")

            if reg.status != "pending":
                raise ValueError("Device code already used")

            # Reuse existing agent or create new one
            existing = await self._dao.find_agent_by_name(reg.agent_name)
            if existing is not None:
                agent = existing
            else:
                agent = await self._dao.create_agent(
                    name=reg.agent_name,
                    robot_type=reg.robot_type,
                    owner_id=owner_id,
                )

            # Generate API key
            plaintext = Crypto.generate_api_key()
            await self._dao.create_api_key(
                key_hash=Crypto.hash_key(plaintext),
                agent_id=agent.id,
            )

            # Update registration
            reg.status = "approved"
            reg.api_key_plaintext = plaintext
            reg.agent_id = agent.id
            await self._dao.commit()

        return {"agent_id": agent.id, "agent_name": agent.name}

    async def resolve_api_key(self, api_key: str) -> Agent:
        """Resolve a plaintext API key to its Agent.

        Raises:
            ValueError: If the key is invalid, revoked, or agent not found.
        """
        key_hash = Crypto.hash_key(api_key)
        async with self._dao.transaction():
            row = await self._dao.find_api_key_by_hash(key_hash)
            if row is None:
                raise ValueError("Invalid API key")
            agent = await self._dao.find_agent_by_id(row.agent_id)
            if agent is None:
                raise ValueError("Agent not found for API key")
            await self._dao.update_agent_last_seen(agent.id)
            await self._dao.commit()
        return agent

    async def list_agents(self, owner_id: str) -> list[dict[str, object]]:
        """Return all agents owned by a user."""
        async with self._dao.transaction():
            agents = await self._dao.list_agents_by_owner(owner_id)
        return [self._agent_to_dict(a) for a in agents]

    async def revoke_agent_key(
        self, agent_id: str, owner_id: str,
    ) -> dict[str, int]:
        """Revoke all API keys for an agent.

        Raises:
            ValueError: If the agent is not found or not owned by the user.
        """
        async with self._dao.transaction():
            agent = await self._dao.find_agent_by_id(agent_id)
            if agent is None:
                raise ValueError("Agent not found")
            if agent.owner_id != owner_id:
                raise ValueError("Not the agent owner")
            count = await self._dao.revoke_api_keys_for_agent(agent_id)
            await self._dao.commit()
        return {"revoked": count}

    async def get_registration_by_user_code(
        self, user_code: str,
    ) -> DeviceRegistration | None:
        """Look up a device registration by user code for the approval page."""
        async with self._dao.transaction():
            return await self._dao.find_registration_by_user_code(user_code)

    @staticmethod
    def _agent_to_dict(agent: Agent) -> dict[str, object]:
        """Serialize an Agent to a JSON-safe dict."""
        return {
            "id": agent.id,
            "name": agent.name,
            "robot_type": agent.robot_type,
            "owner_id": agent.owner_id,
            "status": agent.status,
            "created_at": (
                agent.created_at.isoformat() if agent.created_at else None
            ),
            "last_seen_at": (
                agent.last_seen_at.isoformat() if agent.last_seen_at else None
            ),
        }
