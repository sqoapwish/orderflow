from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from orderflow.modules.audit.domain import AuditActorType


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_event_id: UUID
    action: str
    actor_type: AuditActorType
    actor_id: UUID | None
    actor_role: str | None
    resource_type: str
    resource_id: UUID
    correlation_id: str | None
    details: dict[str, Any]
    occurred_at: datetime
    recorded_at: datetime


class AuditEventPageResponse(BaseModel):
    items: list[AuditEventResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
