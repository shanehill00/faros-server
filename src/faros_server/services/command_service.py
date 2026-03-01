"""Business logic for agent command dispatch."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from faros_server.dao.command_dao import CommandDAO
from faros_server.models.command import AgentCommand
from faros_server.utils.time import Time


class CommandNotFoundError(Exception):
    """Raised when the requested command does not exist."""


class CommandAlreadyAckedError(Exception):
    """Raised when a command has already been acknowledged."""


class CommandNotInProgressError(Exception):
    """Raised when output is posted to a command not in in_progress status."""


class CommandService:
    """Built once at startup with its DAO pre-wired."""

    def __init__(
        self,
        command_dao: CommandDAO,
        command_ttl_seconds: int = 30,
    ) -> None:
        self._dao = command_dao
        self._ttl = timedelta(seconds=command_ttl_seconds)

    async def queue_command(
        self,
        agent_id: str,
        command_type: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Create a pending command for an agent.

        Returns:
            Full command dict for the operator view.
        """
        payload_json = json.dumps(payload) if payload is not None else None
        async with self._dao.transaction():
            command = await self._dao.create_command(
                agent_id=agent_id,
                command_type=command_type,
                payload=payload_json,
            )
            await self._dao.commit()
        return CommandService._command_to_dict(command)

    async def poll_pending(self, agent_id: str) -> list[dict[str, Any]]:
        """Fetch pending commands, expire stale ones, deliver fresh ones.

        Commands older than the configured TTL are marked ``expired`` and
        never delivered to the agent.  Fresh commands are marked
        ``in_progress`` as before.

        Returns:
            List of poll-format dicts for the agent (fresh commands only).
        """
        now = datetime.now(timezone.utc)
        async with self._dao.transaction():
            commands = await self._dao.list_pending(agent_id)
            expired = [
                c for c in commands
                if now - Time.ensure_utc(c.created_at) > self._ttl
            ]
            fresh = [
                c for c in commands
                if now - Time.ensure_utc(c.created_at) <= self._ttl
            ]
            if expired:
                await self._dao.mark_expired([c.id for c in expired])
            if fresh:
                await self._dao.mark_in_progress([c.id for c in fresh])
            if expired or fresh:
                await self._dao.commit()
        return [CommandService._command_to_poll_dict(c) for c in fresh]

    async def acknowledge(
        self,
        agent_id: str,
        command_id: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Store the ack result for a command.

        Raises:
            CommandNotFoundError: If the command does not exist or belongs
                to a different agent.
            CommandAlreadyAckedError: If the command was already acked.
        """
        result_json = json.dumps(result)
        async with self._dao.transaction():
            command = await self._dao.find_by_id(command_id)
            if command is None or command.agent_id != agent_id:
                raise CommandNotFoundError("Command not found")
            if command.status in ("acked", "expired"):
                raise CommandAlreadyAckedError("Command already acknowledged")
            await self._dao.mark_acked(command, result_json)
            await self._dao.commit()
        return CommandService._command_to_dict(command)

    async def list_commands(
        self,
        agent_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List commands for an agent, optionally filtered by status.

        Returns:
            List of full command dicts for the operator view.
        """
        async with self._dao.transaction():
            commands = await self._dao.list_by_agent(agent_id, status=status)
        return [CommandService._command_to_dict(c) for c in commands]

    async def append_output(
        self,
        agent_id: str,
        command_id: str,
        text: str,
    ) -> dict[str, str]:
        """Append output text to an in-progress command.

        Raises:
            CommandNotFoundError: If the command does not exist or belongs
                to a different agent.
            CommandNotInProgressError: If the command is not in_progress.
        """
        async with self._dao.transaction():
            command = await self._dao.find_by_id(command_id)
            if command is None or command.agent_id != agent_id:
                raise CommandNotFoundError("Command not found")
            if command.status != "in_progress":
                raise CommandNotInProgressError(
                    "Command is not in_progress",
                )
            await self._dao.append_output(command, text)
            await self._dao.commit()
        return {"status": "ok"}

    async def get_command(
        self,
        agent_id: str,
        command_id: str,
    ) -> dict[str, Any]:
        """Get a single command by ID.

        Raises:
            CommandNotFoundError: If the command does not exist or belongs
                to a different agent.
        """
        async with self._dao.transaction():
            command = await self._dao.find_by_id(command_id)
        if command is None or command.agent_id != agent_id:
            raise CommandNotFoundError("Command not found")
        return CommandService._command_to_dict(command)

    @staticmethod
    def _command_to_dict(cmd: AgentCommand) -> dict[str, Any]:
        """Serialize a command to a full dict for operator views."""
        return {
            "id": cmd.id,
            "agent_id": cmd.agent_id,
            "type": cmd.type,
            "payload": json.loads(cmd.payload) if cmd.payload else None,
            "status": cmd.status,
            "result": json.loads(cmd.result) if cmd.result else None,
            "output": cmd.output,
            "created_at": (
                cmd.created_at.isoformat() if cmd.created_at else None
            ),
            "delivered_at": (
                cmd.delivered_at.isoformat() if cmd.delivered_at else None
            ),
            "acked_at": (
                cmd.acked_at.isoformat() if cmd.acked_at else None
            ),
        }

    @staticmethod
    def _command_to_poll_dict(cmd: AgentCommand) -> dict[str, Any]:
        """Serialize a command to a minimal dict for agent poll responses."""
        return {
            "command_id": cmd.id,
            "trace_id": cmd.id,
            "type": cmd.type,
            "payload": json.loads(cmd.payload) if cmd.payload else None,
        }
