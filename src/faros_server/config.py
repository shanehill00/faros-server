"""Server configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server settings loaded from environment variables prefixed with FAROS_."""

    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite+aiosqlite:///faros.db"
    token_expire_minutes: int = 60

    model_config = {"env_prefix": "FAROS_"}
