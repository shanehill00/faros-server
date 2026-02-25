"""User request/response schemas."""

from pydantic import BaseModel


class AuthMethodRead(BaseModel):
    """A linked OAuth provider."""

    provider: str
    email: str


class UserRead(BaseModel):
    """User response with linked auth methods."""

    id: str
    name: str | None
    avatar_url: str | None
    is_superuser: bool
    is_active: bool
    auth_methods: list[AuthMethodRead]


class Token(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
