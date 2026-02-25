"""Tests for configuration loading."""

from __future__ import annotations

from unittest.mock import patch

from faros_server.config import ConfigLoader, Settings


def test_settings_direct_construction() -> None:
    """Direct Settings() construction works without YAML (for tests)."""
    s = Settings(secret_key="test", database_url="sqlite+aiosqlite://")
    assert s.secret_key == "test"


def test_load_settings_missing_env_uses_defaults() -> None:
    """load_settings for a nonexistent env falls back to field defaults."""
    with patch.dict("os.environ", {"FAROS_ENV": "nonexistent"}, clear=False):
        s = ConfigLoader.load_settings()
    assert s.secret_key == "change-me-in-production"
    assert s.database_url == "sqlite+aiosqlite:///faros.db"


def test_load_settings_dev_loads_yaml() -> None:
    """load_settings with FAROS_ENV=dev loads from config/dev/settings.yaml."""
    with patch.dict("os.environ", {"FAROS_ENV": "dev"}, clear=False):
        s = ConfigLoader.load_settings()
    assert s.base_url == "http://localhost:8000"


def test_load_settings_explicit_overrides_yaml() -> None:
    """Explicit kwargs to load_settings override YAML values."""
    with patch.dict("os.environ", {"FAROS_ENV": "dev"}, clear=False):
        s = ConfigLoader.load_settings(base_url="http://custom:9000")
    assert s.base_url == "http://custom:9000"


def test_load_settings_env_var_overrides_yaml() -> None:
    """Environment variables override YAML values."""
    env = {"FAROS_ENV": "dev", "FAROS_BASE_URL": "http://from-env:7000"}
    with patch.dict("os.environ", env, clear=False):
        s = ConfigLoader.load_settings()
    assert s.base_url == "http://from-env:7000"
