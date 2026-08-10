from uuid import uuid4

import pytest
from argon2 import PasswordHasher

from orderflow.core.config import Settings
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.security import (
    PasswordService,
    TokenDecodeError,
    TokenService,
    hash_refresh_token,
    refresh_token_matches,
)


def test_passwords_are_hashed_with_argon2() -> None:
    passwords = PasswordService(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))

    password_hash = passwords.hash("Strong-password-42")

    assert password_hash.startswith("$argon2id$")
    assert "Strong-password-42" not in password_hash
    assert passwords.verify("Strong-password-42", password_hash) is True
    assert passwords.verify("wrong-password", password_hash) is False
    assert passwords.verify("password", "not-an-argon2-hash") is False


def test_access_and_refresh_tokens_have_separate_types(test_settings: Settings) -> None:
    tokens = TokenService(test_settings)
    user_id = uuid4()
    session_id = uuid4()

    access_token = tokens.create_access_token(user_id, UserRole.MANAGER)
    refresh_token = tokens.create_refresh_token(user_id, session_id)

    assert tokens.decode_access_token(access_token).user_id == user_id
    assert tokens.decode_access_token(access_token).role is UserRole.MANAGER
    assert tokens.decode_refresh_token(refresh_token).session_id == session_id
    with pytest.raises(TokenDecodeError):
        tokens.decode_access_token(refresh_token)
    with pytest.raises(TokenDecodeError):
        tokens.decode_refresh_token(access_token)


def test_tampered_token_is_rejected(test_settings: Settings) -> None:
    tokens = TokenService(test_settings)
    access_token = tokens.create_access_token(uuid4(), UserRole.CUSTOMER)
    header, payload, signature = access_token.split(".")
    replacement = "a" if signature[0] != "a" else "b"
    tampered_token = f"{header}.{payload}.{replacement}{signature[1:]}"

    with pytest.raises(TokenDecodeError):
        tokens.decode_access_token(tampered_token)


def test_refresh_token_hash_comparison() -> None:
    token_hash = hash_refresh_token("refresh-token")

    assert len(token_hash) == 64
    assert refresh_token_matches("refresh-token", token_hash) is True
    assert refresh_token_matches("different-token", token_hash) is False
