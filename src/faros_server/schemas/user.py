"""User request/response schemas."""

from pydantic import BaseModel


class UserRead(BaseModel):
    """User response."""

    id: str
    email: str
    name: str | None
    provider: str
    is_superuser: bool
    is_active: bool


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
