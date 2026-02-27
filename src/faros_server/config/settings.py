"""Settings model — pydantic-settings with env var support."""

from __future__ import annotations

from pydantic_settings import BaseSettings

ENV_PREFIX = "FAROS_"


class Settings(BaseSettings):
    """Server settings.

    Use ``ConfigLoader.load_settings()`` to build with YAML + env var layering.
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
    device_code_expire_minutes: int = 15
    device_poll_interval: int = 5

    model_config = {"env_prefix": ENV_PREFIX}
