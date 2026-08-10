import os
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="set RUN_INTEGRATION_TESTS=1 with infrastructure running",
)
async def test_auth_flow_with_postgresql() -> None:
    app = create_app(Settings(_env_file=None))
    email = f"integration-{uuid4()}@example.com"

    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        registered_response = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "Integration-password-42"},
        )
        assert registered_response.status_code == 201, registered_response.text
        registered = registered_response.json()

        login_response = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Integration-password-42"},
        )
        assert login_response.status_code == 200, login_response.text
        logged_in = login_response.json()

        me_response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {logged_in['tokens']['access_token']}"},
        )
        assert me_response.status_code == 200, me_response.text
        assert me_response.json()["id"] == registered["user"]["id"]

        refresh_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": logged_in["tokens"]["refresh_token"]},
        )
        assert refresh_response.status_code == 200, refresh_response.text

        replay_response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": logged_in["tokens"]["refresh_token"]},
        )
        assert replay_response.status_code == 401, replay_response.text
