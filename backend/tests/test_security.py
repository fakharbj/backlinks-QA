"""Auth/crypto primitive tests (PRD §9.4)."""

import jwt
import pytest

from app.core.security import (
    create_token,
    decode_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("s3cret-password!")
    assert hashed != "s3cret-password!"
    assert verify_password("s3cret-password!", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_roundtrip():
    token, jti, _ = create_token(
        subject="user-1", token_type="access", workspace_id="ws-1", role="admin"
    )
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-1"
    assert payload["ws"] == "ws-1"
    assert payload["role"] == "admin"
    assert payload["jti"] == jti


def test_token_type_is_enforced():
    refresh, _, _ = create_token(subject="user-1", token_type="refresh")
    with pytest.raises(jwt.PyJWTError):
        decode_token(refresh, expected_type="access")


def test_secret_encryption_roundtrip():
    cipher = encrypt_secret("xoxb-slack-token")
    assert cipher != "xoxb-slack-token"
    assert decrypt_secret(cipher) == "xoxb-slack-token"
