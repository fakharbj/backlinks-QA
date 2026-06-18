"""Password hashing, JWT issue/verify, and secret encryption.

- Passwords: Argon2id (PRD §9.4).
- Tokens: short-lived access JWT + long-lived rotating refresh JWT, both carrying
  a ``jti`` so refresh tokens can be revoked via a Redis denylist on logout.
- Integration credentials (SMTP/Slack/API keys): Fernet envelope encryption at
  rest so they never sit in the DB in cleartext.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet

from app.core.config import settings

# Argon2id with sensible interactive-auth parameters.
_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4)

TokenType = Literal["access", "refresh"]


# ── Passwords ─────────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(hashed: str) -> bool:
    try:
        return _ph.check_needs_rehash(hashed)
    except (InvalidHashError, ValueError):
        return True


# ── JWT ───────────────────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_token(
    *,
    subject: str | uuid.UUID,
    token_type: TokenType,
    workspace_id: str | uuid.UUID | None = None,
    role: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Return ``(encoded_jwt, jti, expires_at)``."""
    jti = uuid.uuid4().hex
    if token_type == "access":
        expires = _now() + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
    else:
        expires = _now() + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": jti,
        "iat": int(_now().timestamp()),
        "exp": int(expires.timestamp()),
    }
    if workspace_id is not None:
        payload["ws"] = str(workspace_id)
    if role is not None:
        payload["role"] = role
    if extra:
        payload.update(extra)

    encoded = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return encoded, jti, expires


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """Decode and validate signature/expiry. Raises ``jwt.PyJWTError`` on failure."""
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub", "type", "jti"]},
    )
    if expected_type is not None and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload


# ── Password-reset / opaque tokens ─────────────────────────────────────────────
def generate_opaque_token() -> tuple[str, str]:
    """Return ``(clear_token, sha256_hex)``. Store only the hash."""
    clear = secrets.token_urlsafe(32)
    digest = hashlib.sha256(clear.encode()).hexdigest()
    return clear, digest


def hash_opaque_token(clear: str) -> str:
    return hashlib.sha256(clear.encode()).hexdigest()


# ── Secret encryption (integration credentials) ─────────────────────────────────
def _fernet() -> Fernet:
    # Derive a stable 32-byte urlsafe key from the configured secret.
    key = settings.SECRETS_ENCRYPTION_KEY.encode()
    if len(key) != 44 or not key.endswith(b"="):  # not already a Fernet key
        key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
