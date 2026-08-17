from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AuditActorType(StrEnum):
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class AuditFilters:
    page: int = 1
    page_size: int = 20
    action: str | None = None
    actor_id: UUID | None = None
    resource_type: str | None = None
    resource_id: UUID | None = None
    correlation_id: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
