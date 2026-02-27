"""Cryptographic helpers for API keys and device codes."""

from __future__ import annotations

import hashlib
import secrets
import string

_USER_CODE_ALPHABET = string.ascii_uppercase + string.digits
_API_KEY_PREFIX = "fk_"


class Crypto:
    """Static helpers for key generation and hashing."""

    @staticmethod
    def generate_user_code() -> str:
        """Generate XXXX-XXXX user code (uppercase alphanumeric)."""
        left = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(4))
        right = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(4))
        return f"{left}-{right}"

    @staticmethod
    def generate_api_key() -> str:
        """Generate a plaintext API key with the ``fk_`` prefix."""
        return _API_KEY_PREFIX + secrets.token_urlsafe(32)

    @staticmethod
    def hash_key(plaintext: str) -> str:
        """SHA-256 hash of a plaintext API key."""
        return hashlib.sha256(plaintext.encode()).hexdigest()
