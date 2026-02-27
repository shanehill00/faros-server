"""Tests for CLI entry point."""

from __future__ import annotations

import subprocess
import sys

import pytest

from faros_server.app import CLI


def test_parser_run_defaults() -> None:
    """Parser parses 'run' with defaults."""
    parser = CLI._build_parser()
    args = parser.parse_args(["run"])
    assert args.command == "run"
    assert args.host == "0.0.0.0"
    assert args.port == 8000


def test_cli_no_command_exits(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI with no command prints help and exits 1."""
    with pytest.raises(SystemExit) as exc_info:
        CLI.main([])
    assert exc_info.value.code == 1


def test_cli_entry_point_installed() -> None:
    """faros-server entry point is callable."""
    result = subprocess.run(
        [sys.executable, "-m", "faros_server.app"],
        capture_output=True, text=True, timeout=5,
    )
    # Should print help (no command given) and exit 1
    assert result.returncode == 1
