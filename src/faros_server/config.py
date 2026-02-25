"""Server configuration — YAML file per environment, env vars override."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings

# Repo root / config / <env> / settings.yaml
_CONFIG_ROOT = Path(__file__).resolve().parents[1] / "config"


def _load_yaml(env: str) -> dict[str, Any]:
    """Load the settings.yaml for the given environment."""
    path = _CONFIG_ROOT / env / "settings.yaml"
    if not path.exists():
        return {}
    with path.open() as config_file:
        data = yaml.safe_load(config_file)
    return data if isinstance(data, dict) else {}


_ENV_PREFIX = "FAROS_"


def load_settings(**overrides: Any) -> Settings:
    """Build Settings with proper priority: overrides > env vars > YAML > defaults.

    YAML values are only used for fields that don't have a corresponding
    environment variable set, so env vars always win.
    """
    env = os.environ.get("FAROS_ENV", "dev")
    yaml_values = _load_yaml(env)
    # Drop YAML keys that have a corresponding env var — env vars must win,
    # and pydantic-settings treats __init__ kwargs as highest priority.
    filtered: dict[str, Any] = {}
    for key, value in yaml_values.items():
        env_key = f"{_ENV_PREFIX}{key.upper()}"
        if env_key not in os.environ:
            filtered[key] = value
    merged = {**filtered, **overrides}
    return Settings(**merged)


class Settings(BaseSettings):
    """Server settings.

    Use ``load_settings()`` to build with YAML + env var layering.
    Direct construction (e.g. in tests) skips YAML loading.
    """

    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite+aiosqlite:///faros.db"
    jwt_algorithm: str = "HS256"
    token_expire_minutes: int = 60
    base_url: str = "http://localhost:8000"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_url: str = "https://oauth2.googleapis.com/token"
    google_userinfo_url: str = "https://www.googleapis.com/oauth2/v2/userinfo"

    model_config = {"env_prefix": _ENV_PREFIX}
