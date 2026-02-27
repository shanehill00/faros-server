"""Auth resource — protocol-agnostic authentication and user operations."""

from __future__ import annotations

import base64
import json
import secrets

from faros_server.clients.google_oauth_client import GoogleOAuthClient
from faros_server.models.user import User
from faros_server.services.user_service import UserService
from faros_server.utils.jwt import JWTManager


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
        user_service: UserService,
        oauth_client: GoogleOAuthClient,
    ) -> None:
        self._user_service = user_service
        self._oauth_client = oauth_client

    @staticmethod
    def _validate_provider(provider: str) -> None:
        """Raise UnsupportedProviderError if the provider is not in the supported set."""
        if provider not in _SUPPORTED_PROVIDERS:
            raise UnsupportedProviderError(f"Unsupported provider: {provider}")

    def login_url(self, provider: str) -> str:
        """Build the OAuth authorization URL for the given provider.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            OAuthNotConfiguredError: If OAuth credentials are not set.
        """
        self._validate_provider(provider)
        if not self._oauth_client.is_configured:
            raise OAuthNotConfiguredError("Google OAuth not configured")
        state = secrets.token_urlsafe(32)
        return self._oauth_client.authorization_url(
            redirect_uri=self._oauth_client.callback_uri,
            state=state,
        )

    def device_login_url(self, provider: str, next_path: str) -> str:
        """Build OAuth URL for device-flow approval. Encodes next_path in state.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            OAuthNotConfiguredError: If OAuth credentials are not set.
        """
        self._validate_provider(provider)
        if not self._oauth_client.is_configured:
            raise OAuthNotConfiguredError("Google OAuth not configured")
        state_data = json.dumps({"next": next_path, "csrf": secrets.token_urlsafe(16)})
        state = base64.urlsafe_b64encode(state_data.encode()).decode()
        return self._oauth_client.authorization_url(
            redirect_uri=self._oauth_client.callback_uri,
            state=state,
        )

    async def callback(self, provider: str, code: str) -> dict[str, str]:
        """Exchange an OAuth code, find/create user, return JWT.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            AuthError: If code exchange fails or user is inactive.
        """
        self._validate_provider(provider)
        try:
            info = await self._oauth_client.exchange_code(
                code=code, redirect_uri=self._oauth_client.callback_uri,
            )
        except ValueError as error:
            raise AuthError(str(error)) from error
        user = await self._user_service.find_or_create_user(info)
        if not user.is_active:
            raise AuthError("User account is inactive")
        token = JWTManager.create_token({"sub": user.id})
        return {"access_token": token, "token_type": "bearer"}

    async def resolve_token(self, token: str) -> User:
        """Decode a JWT and return the corresponding active user.

        Raises:
            ValueError: If the token is invalid or the user is not found/inactive.
        """
        payload = JWTManager.decode_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("Invalid token payload: missing sub claim")
        user = await self._user_service.find_by_id(str(user_id))
        if user is None or not user.is_active:
            raise ValueError("User not found or inactive")
        return user

    async def me(self, user: User) -> dict[str, object]:
        """Return the authenticated user with linked auth methods."""
        return await self._user_service.load_user_response(user)

    def link_url(self, provider: str) -> str:
        """Build the OAuth authorization URL for account linking.

        Raises:
            UnsupportedProviderError: If the provider is not supported.
            OAuthNotConfiguredError: If OAuth credentials are not set.
        """
        self._validate_provider(provider)
        if not self._oauth_client.is_configured:
            raise OAuthNotConfiguredError("Google OAuth not configured")
        state = secrets.token_urlsafe(32)
        return self._oauth_client.authorization_url(
            redirect_uri=self._oauth_client.link_callback_uri,
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
        self._validate_provider(provider)
        try:
            info = await self._oauth_client.exchange_code(
                code=code, redirect_uri=self._oauth_client.link_callback_uri,
            )
        except ValueError as error:
            raise AuthError(str(error)) from error
        try:
            return await self._user_service.link_auth_method(user, info)
        except ValueError as error:
            raise DuplicateLinkError(str(error)) from error


