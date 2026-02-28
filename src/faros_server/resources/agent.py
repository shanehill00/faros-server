"""Agent resource — protocol-agnostic device flow and agent management."""

from __future__ import annotations

from datetime import datetime, timezone

from faros_server.models.user import User
from faros_server.services.agent_service import AgentService
from faros_server.utils.time import Time


class DeviceFlowExpiredError(Exception):
    """Raised when a device code has expired."""


class DeviceFlowNotFoundError(Exception):
    """Raised when a device or user code is unknown."""


class DeviceFlowAlreadyUsedError(Exception):
    """Raised when a device code has already been approved."""


class AgentNotFoundError(Exception):
    """Raised when the requested agent does not exist."""


class AgentNotOwnedError(Exception):
    """Raised when the user does not own the agent."""


class AgentResource:
    """Device-flow registration and agent management.

    Built once at startup with all dependencies pre-wired.
    """

    def __init__(self, *, agent_service: AgentService, base_url: str) -> None:
        self._service = agent_service
        self._base_url = base_url

    async def start_device_flow(
        self, agent_name: str, robot_type: str,
    ) -> dict[str, str | int]:
        """Initiate device-flow registration.

        Returns:
            Dict with device_code, user_code, expires_in, interval,
            and verification_url.
        """
        result = await self._service.start_device_flow(agent_name, robot_type)
        user_code = result["user_code"]
        result["verification_url"] = (
            f"{self._base_url}/api/agents/device/{user_code}"
        )
        return result

    async def poll_device_flow(
        self, device_code: str,
    ) -> dict[str, str]:
        """Poll for device-flow completion.

        Raises:
            DeviceFlowNotFoundError: If device_code is unknown.
        """
        try:
            return await self._service.poll_device_flow(device_code)
        except ValueError as error:
            raise DeviceFlowNotFoundError(str(error)) from error

    async def approve_device(
        self, user_code: str, user: User,
    ) -> dict[str, str]:
        """Approve a pending device registration.

        Raises:
            DeviceFlowNotFoundError: If user_code is unknown.
            DeviceFlowExpiredError: If the device code has expired.
            DeviceFlowAlreadyUsedError: If already approved.
        """
        try:
            return await self._service.approve_device(user_code, user.id)
        except ValueError as error:
            message = str(error)
            if "expired" in message.lower():
                raise DeviceFlowExpiredError(message) from error
            if "already used" in message.lower():
                raise DeviceFlowAlreadyUsedError(message) from error
            raise DeviceFlowNotFoundError(message) from error

    async def deny_device(
        self, user_code: str, user: User,
    ) -> dict[str, str]:
        """Deny a pending device registration.

        Raises:
            DeviceFlowNotFoundError: If user_code is unknown.
            DeviceFlowExpiredError: If the device code has expired.
            DeviceFlowAlreadyUsedError: If already approved or denied.
        """
        try:
            return await self._service.deny_device(user_code)
        except ValueError as error:
            message = str(error)
            if "expired" in message.lower():
                raise DeviceFlowExpiredError(message) from error
            if "already used" in message.lower():
                raise DeviceFlowAlreadyUsedError(message) from error
            raise DeviceFlowNotFoundError(message) from error

    async def device_page(
        self, user_code: str,
    ) -> dict[str, str]:
        """Get info for the device approval page.

        Raises:
            DeviceFlowNotFoundError: If user_code is unknown.
            DeviceFlowExpiredError: If the device code has expired.
        """
        reg = await self._service.get_registration_by_user_code(user_code)
        if reg is None:
            raise DeviceFlowNotFoundError("Unknown user code")
        now = datetime.now(timezone.utc)
        if now > Time.ensure_utc(reg.expires_at):
            raise DeviceFlowExpiredError("Device code has expired")
        return {
            "user_code": reg.user_code,
            "agent_name": reg.agent_name,
            "robot_type": reg.robot_type,
            "status": reg.status,
        }

    async def agent_logout(self, api_key: str) -> dict[str, int]:
        """Revoke all keys for the agent identified by the given API key.

        Raises:
            AgentNotFoundError: If the API key is invalid.
        """
        try:
            agent = await self._service.resolve_api_key(api_key)
        except ValueError as error:
            raise AgentNotFoundError(str(error)) from error
        return await self._service.revoke_agent_key(agent.id, agent.owner_id)

    async def list_agents(self, user: User) -> list[dict[str, object]]:
        """Return all agents owned by the authenticated user."""
        return await self._service.list_agents(user.id)

    async def revoke_key(
        self, agent_id: str, user: User,
    ) -> dict[str, int]:
        """Revoke all API keys for an agent.

        Raises:
            AgentNotFoundError: If the agent does not exist.
            AgentNotOwnedError: If the user does not own the agent.
        """
        try:
            return await self._service.revoke_agent_key(agent_id, user.id)
        except ValueError as error:
            message = str(error)
            if "not found" in message.lower():
                raise AgentNotFoundError(message) from error
            raise AgentNotOwnedError(message) from error
