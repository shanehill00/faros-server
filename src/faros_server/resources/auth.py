"""Auth resource — protocol-agnostic authentication and user operations."""

from __future__ import annotations

import secrets

from faros_server.models.user import User
from faros_server.services.user_service import UserService
from faros_server.utils.jwt import JWTManager
from faros_server.utils.oauth import GoogleOAuthClient


class UnsupportedProviderError(Exception):
    """Raised when the requested OAuth provider is not supported."""


class OAuthNotConfiguredError(Exception):
    """Raised when OAuth credentials are missing."""


class AuthError(Exception):
    """Raised for authentication/authorization failures."""


class DuplicateLinkError(Exception):
    """Raised when an auth method is already linked."""


_SUPPORTED_PROVIDERS = frozenset({"google"})


class AuthResource:
    """Authentication and user account operations.

    Built once at startup with all dependencies pre-wired.
    """

    def __init__(
        self,
        *,
        svc: UserService,
        oauth: GoogleOAuthClient,
        jwt: JWTManager,
    ) -> None:
        self._svc = svc
        self._oauth = oauth
        self._jwt = jwt

    def login_url(self, provider: str) -> str:
        """Build the OAuth authorization URL for the given provider.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            OAuthNotConfiguredError: If OAuth credentials are not set.
        """
        _validate_provider(provider)
        if not self._oauth.is_configured:
            raise OAuthNotConfiguredError("Google OAuth not configured")
        state = secrets.token_urlsafe(32)
        return self._oauth.authorization_url(
            redirect_uri=self._oauth.callback_uri(provider),
            state=state,
        )

    async def callback(self, provider: str, code: str) -> dict[str, str]:
        """Exchange an OAuth code, find/create user, return JWT.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            AuthError: If code exchange fails or user is inactive.
        """
        _validate_provider(provider)
        try:
            info = await self._oauth.exchange_code(
                code=code, redirect_uri=self._oauth.callback_uri(provider),
            )
        except ValueError as exc:
            raise AuthError(str(exc)) from exc
        user = await self._svc.find_or_create_user(info)
        if not user.is_active:
            raise AuthError("User account is inactive")
        token = self._jwt.create_token({"sub": user.id})
        return {"access_token": token, "token_type": "bearer"}

    async def me(self, user: User) -> dict[str, object]:
        """Return the authenticated user with linked auth methods."""
        return await self._svc.load_user_response(user)

    def link_url(self, provider: str) -> str:
        """Build the OAuth authorization URL for account linking.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            OAuthNotConfiguredError: If OAuth credentials are not set.
        """
        _validate_provider(provider)
        if not self._oauth.is_configured:
            raise OAuthNotConfiguredError("Google OAuth not configured")
        state = secrets.token_urlsafe(32)
        return self._oauth.authorization_url(
            redirect_uri=self._oauth.link_callback_uri(provider),
            state=state,
        )

    async def link_callback(
        self, provider: str, code: str, user: User,
    ) -> dict[str, object]:
        """Exchange code and link the OAuth account to an existing user.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            AuthError: If code exchange fails.
            DuplicateLinkError: If the provider account is already linked.
        """
        _validate_provider(provider)
        try:
            info = await self._oauth.exchange_code(
                code=code, redirect_uri=self._oauth.link_callback_uri(provider),
            )
        except ValueError as exc:
            raise AuthError(str(exc)) from exc
        try:
            return await self._svc.link_auth_method(user, info)
        except ValueError as exc:
            raise DuplicateLinkError(str(exc)) from exc


def _validate_provider(provider: str) -> None:
    """Raise UnsupportedProviderError if the provider is not in the supported set."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise UnsupportedProviderError(f"Unsupported provider: {provider}")
