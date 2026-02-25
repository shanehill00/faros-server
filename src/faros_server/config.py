"""Server configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server settings loaded from environment variables prefixed with FAROS_."""

    secret_key: str = "change-me-in-production"
    database_url: str = "sqlite+aiosqlite:///faros.db"
    token_expire_minutes: int = 60
    base_url: str = "http://localhost:8000"
    google_client_id: str = ""
    google_client_secret: str = ""

    model_config = {"env_prefix": "FAROS_"}
