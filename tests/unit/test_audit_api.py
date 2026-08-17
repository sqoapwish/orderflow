from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from orderflow.core.config import Settings
from orderflow.main import create_app
from orderflow.modules.audit.dependencies import get_audit_service
from orderflow.modules.audit.service import AuditDomainEventHandler, AuditService
from orderflow.modules.auth.dependencies import get_auth_service
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.schemas.health import ComponentHealth
from tests.fakes import FakeAuditRepository, build_auth_service


class HealthyChecker:
    async def check(self) -> dict[str, ComponentHealth]:
        return {}


@dataclass(slots=True)
class AuditApiContext:
    client: AsyncClient
    repository: FakeAuditRepository
    actor: User
    token: str


@pytest.fixture
async def audit_api(test_settings: Settings) -> AsyncIterator[AuditApiContext]:
    auth_service, _, _, _ = build_auth_service(test_settings)
    registration = await auth_service.register(
        "audit-admin@example.com",
        "Strong-password-42",
    )
    registration.user.role = UserRole.ADMIN
    audit_repository = FakeAuditRepository()
    aggregate_id = uuid4()
    await AuditDomainEventHandler(audit_repository).handle(
        event_id=uuid4(),
        event_type="payment.refunded",
        aggregate_type="payment",
        aggregate_id=aggregate_id,
        payload={
            "actor_id": str(registration.user.id),
            "actor_role": "admin",
            "order_id": str(uuid4()),
            "refund_id": str(uuid4()),
            "amount_minor": 2500,
            "currency": "RUB",
            "status": "refunded",
        },
        occurred_at="2026-08-17T13:00:00+00:00",
        correlation_id="audit-api-42",
    )
    app = create_app(test_settings, readiness_checker=HealthyChecker())
    app.dependency_overrides[get_auth_service] = lambda: auth_service
    app.dependency_overrides[get_audit_service] = lambda: AuditService(audit_repository)
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield AuditApiContext(
            client=client,
            repository=audit_repository,
            actor=registration.user,
            token=registration.tokens.access_token,
        )


async def test_admin_can_filter_and_read_audit_events(audit_api: AuditApiContext) -> None:
    headers = {"Authorization": f"Bearer {audit_api.token}"}
    page = await audit_api.client.get(
        "/api/v1/audit/events",
        headers=headers,
        params={"action": "payment.refunded", "correlation_id": "audit-api-42"},
    )

    assert page.status_code == 200
    payload = page.json()
    assert payload["total"] == 1
    assert payload["items"][0]["actor_role"] == "admin"
    assert payload["items"][0]["details"]["status"] == "refunded"

    event_id = payload["items"][0]["id"]
    detail = await audit_api.client.get(f"/api/v1/audit/events/{event_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == event_id


async def test_audit_api_is_admin_only_and_uses_standard_not_found_error(
    audit_api: AuditApiContext,
) -> None:
    headers = {"Authorization": f"Bearer {audit_api.token}"}
    audit_api.actor.role = UserRole.CUSTOMER
    forbidden = await audit_api.client.get("/api/v1/audit/events", headers=headers)

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "insufficient_role"

    audit_api.actor.role = UserRole.ADMIN
    missing = await audit_api.client.get(
        f"/api/v1/audit/events/{uuid4()}",
        headers=headers,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "audit_event_not_found"


async def test_audit_api_rejects_inverted_time_range(audit_api: AuditApiContext) -> None:
    response = await audit_api.client.get(
        "/api/v1/audit/events",
        headers={"Authorization": f"Bearer {audit_api.token}"},
        params={
            "occurred_from": "2026-08-18T00:00:00Z",
            "occurred_to": "2026-08-17T00:00:00Z",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_audit_time_range"
