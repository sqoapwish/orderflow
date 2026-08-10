from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.auth.dependencies import get_auth_service, require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.errors import InsufficientRoleError
from orderflow.schemas.health import ComponentHealth
from tests.fakes import build_auth_service


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@pytest.fixture
async def auth_client(test_settings: Settings) -> AsyncIterator[AsyncClient]:
    service, _, _, _ = build_auth_service(test_settings)
    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: service
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


async def test_complete_auth_api_flow(auth_client: AsyncClient) -> None:
    register_response = await auth_client.post(
        "/api/v1/auth/register",
        json={"email": "Customer@Example.com", "password": "Strong-password-42"},
    )

    assert register_response.status_code == 201
    registered = register_response.json()
    assert registered["user"]["email"] == "customer@example.com"
    assert registered["user"]["role"] == "customer"
    assert registered["tokens"]["token_type"] == "bearer"
    assert registered["tokens"]["expires_in"] == 900

    me_response = await auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registered['tokens']['access_token']}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["id"] == registered["user"]["id"]

    refresh_response = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": registered["tokens"]["refresh_token"]},
    )
    assert refresh_response.status_code == 200
    rotated = refresh_response.json()
    assert rotated["refresh_token"] != registered["tokens"]["refresh_token"]

    logout_response = await auth_client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert logout_response.status_code == 204
    assert logout_response.content == b""

    rejected_refresh = await auth_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": rotated["refresh_token"]},
    )
    assert rejected_refresh.status_code == 401
    assert rejected_refresh.json()["error"]["code"] == "invalid_refresh_token"


async def test_login_validation_and_auth_errors_use_standard_envelope(
    auth_client: AsyncClient,
) -> None:
    invalid_request = await auth_client.post(
        "/api/v1/auth/register",
        json={"email": "invalid", "password": "short"},
    )
    invalid_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )
    missing_bearer = await auth_client.get("/api/v1/auth/me")

    assert invalid_request.status_code == 422
    assert invalid_request.json()["error"]["code"] == "validation_error"
    assert invalid_login.status_code == 401
    assert invalid_login.json()["error"]["code"] == "invalid_credentials"
    assert invalid_login.headers["www-authenticate"] == "Bearer"
    assert missing_bearer.status_code == 401
    assert missing_bearer.json()["error"]["code"] == "invalid_access_token"


async def test_role_dependency_allows_only_configured_roles(test_settings: Settings) -> None:
    service, _, _, _ = build_auth_service(test_settings)
    result = await service.register("customer@example.com", "Strong-password-42")
    admin_only = require_roles(UserRole.ADMIN)

    with pytest.raises(InsufficientRoleError):
        await admin_only(result.user)

    result.user.role = UserRole.ADMIN
    assert await admin_only(result.user) is result.user
