from datetime import UTC, datetime, timedelta

import pytest

from orderflow.core.config import Settings
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.errors import (
    EmailAlreadyRegisteredError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)
from orderflow.modules.auth.security import hash_refresh_token
from tests.fakes import build_auth_service


async def test_register_creates_customer_and_server_side_session(test_settings: Settings) -> None:
    service, repository, passwords, tokens = build_auth_service(test_settings)

    result = await service.register("customer@example.com", "Strong-password-42")

    assert result.user.role is UserRole.CUSTOMER
    assert passwords.verify("Strong-password-42", result.user.password_hash) is True
    assert result.tokens.expires_in == 900
    refresh_claims = tokens.decode_refresh_token(result.tokens.refresh_token)
    session = repository.sessions[refresh_claims.session_id]
    assert session.user_id == result.user.id
    assert session.token_hash == hash_refresh_token(result.tokens.refresh_token)
    assert result.tokens.refresh_token not in session.token_hash


async def test_duplicate_registration_is_rejected(test_settings: Settings) -> None:
    service, _, _, _ = build_auth_service(test_settings)
    await service.register("customer@example.com", "Strong-password-42")

    with pytest.raises(EmailAlreadyRegisteredError):
        await service.register("customer@example.com", "Another-password-42")


@pytest.mark.parametrize("password", ["wrong-password", "Strong-password-41"])
async def test_login_rejects_wrong_password(test_settings: Settings, password: str) -> None:
    service, _, _, _ = build_auth_service(test_settings)
    await service.register("customer@example.com", "Strong-password-42")

    with pytest.raises(InvalidCredentialsError):
        await service.login("customer@example.com", password)


async def test_login_and_access_authentication_use_current_database_user(
    test_settings: Settings,
) -> None:
    service, _, _, tokens = build_auth_service(test_settings)
    registered = await service.register("manager@example.com", "Strong-password-42")
    registered.user.role = UserRole.MANAGER

    logged_in = await service.login("manager@example.com", "Strong-password-42")
    authenticated_user = await service.authenticate_access_token(logged_in.tokens.access_token)

    assert tokens.decode_access_token(logged_in.tokens.access_token).role is UserRole.MANAGER
    assert authenticated_user is registered.user
    assert authenticated_user.role is UserRole.MANAGER


async def test_inactive_user_cannot_login_or_use_access_token(test_settings: Settings) -> None:
    service, _, _, _ = build_auth_service(test_settings)
    registered = await service.register("inactive@example.com", "Strong-password-42")
    registered.user.is_active = False

    with pytest.raises(InvalidCredentialsError):
        await service.login("inactive@example.com", "Strong-password-42")
    with pytest.raises(InvalidAccessTokenError):
        await service.authenticate_access_token(registered.tokens.access_token)


async def test_refresh_rotates_token_and_reuse_revokes_session(test_settings: Settings) -> None:
    service, repository, _, tokens = build_auth_service(test_settings)
    registered = await service.register("customer@example.com", "Strong-password-42")
    first_refresh_token = registered.tokens.refresh_token
    claims = tokens.decode_refresh_token(first_refresh_token)

    rotated = await service.refresh(first_refresh_token)

    assert rotated.refresh_token != first_refresh_token
    assert repository.sessions[claims.session_id].last_used_at is not None
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(first_refresh_token)
    assert repository.sessions[claims.session_id].revoked_at is not None
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(rotated.refresh_token)


async def test_expired_refresh_session_is_rejected(test_settings: Settings) -> None:
    service, repository, _, tokens = build_auth_service(test_settings)
    registered = await service.register("customer@example.com", "Strong-password-42")
    claims = tokens.decode_refresh_token(registered.tokens.refresh_token)
    repository.sessions[claims.session_id].expires_at = datetime.now(UTC) - timedelta(seconds=1)

    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(registered.tokens.refresh_token)


async def test_logout_is_idempotent_and_revokes_refresh_session(test_settings: Settings) -> None:
    service, repository, _, tokens = build_auth_service(test_settings)
    registered = await service.register("customer@example.com", "Strong-password-42")
    claims = tokens.decode_refresh_token(registered.tokens.refresh_token)

    await service.logout(registered.tokens.refresh_token)
    await service.logout(registered.tokens.refresh_token)
    await service.logout("not-a-token")

    assert repository.sessions[claims.session_id].revoked_at is not None
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh(registered.tokens.refresh_token)


async def test_invalid_access_and_refresh_tokens_are_rejected(test_settings: Settings) -> None:
    service, _, _, _ = build_auth_service(test_settings)

    with pytest.raises(InvalidAccessTokenError):
        await service.authenticate_access_token("invalid-token")
    with pytest.raises(InvalidRefreshTokenError):
        await service.refresh("invalid-token")
