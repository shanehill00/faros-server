"""ConfigLoader — YAML file per environment, env vars override."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from faros_server.config.settings import ENV_PREFIX, Settings

_CONFIG_ROOT = Path(__file__).resolve().parent


class ConfigLoader:
    """Load settings from YAML files with environment variable overrides."""

    @staticmethod
    def _load_yaml(env: str) -> dict[str, Any]:
        """Load the settings.yaml for the given environment."""
        path = _CONFIG_ROOT / env / "settings.yaml"
        if not path.exists():
            return {}
        with path.open() as config_file:
            data = yaml.safe_load(config_file)
        return data if isinstance(data, dict) else {}

    @staticmethod
    def load_settings(**overrides: Any) -> Settings:
        """Build Settings with proper priority: overrides > env vars > YAML > defaults.

        YAML values are only used for fields that don't have a corresponding
        environment variable set, so env vars always win.
        """
        env = os.environ.get("FAROS_ENV", "dev")
        yaml_values = ConfigLoader._load_yaml(env)
        # Drop YAML keys that have a corresponding env var — env vars must win,
        # and pydantic-settings treats __init__ kwargs as highest priority.
        filtered: dict[str, Any] = {}
        for key, value in yaml_values.items():
            env_key = f"{ENV_PREFIX}{key.upper()}"
            if env_key not in os.environ:
                filtered[key] = value
        merged = {**filtered, **overrides}
        return Settings(**merged)
