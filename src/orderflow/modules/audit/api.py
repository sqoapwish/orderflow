from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from orderflow.modules.audit.dependencies import get_audit_service
from orderflow.modules.audit.domain import AuditFilters
from orderflow.modules.audit.schemas import AuditEventPageResponse, AuditEventResponse
from orderflow.modules.audit.service import AuditService
from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User

router = APIRouter()

AuditServiceDependency = Annotated[AuditService, Depends(get_audit_service)]
AuditAdminDependency = Annotated[User, Depends(require_roles(UserRole.ADMIN))]


@router.get("", response_model=AuditEventPageResponse, summary="List immutable audit events")
async def list_audit_events(
    service: AuditServiceDependency,
    _: AuditAdminDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    action: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    actor_id: UUID | None = None,
    resource_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    resource_id: UUID | None = None,
    correlation_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> AuditEventPageResponse:
    result = await service.list_events(
        AuditFilters(
            page=page,
            page_size=page_size,
            action=action,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            correlation_id=correlation_id,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
    )
    return AuditEventPageResponse(
        items=[AuditEventResponse.model_validate(event) for event in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{event_id}",
    response_model=AuditEventResponse,
    summary="Get an immutable audit event",
)
async def get_audit_event(
    event_id: UUID,
    service: AuditServiceDependency,
    _: AuditAdminDependency,
) -> AuditEventResponse:
    return AuditEventResponse.model_validate(await service.get_event(event_id))
