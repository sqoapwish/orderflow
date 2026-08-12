from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"


@dataclass(frozen=True, slots=True)
class OrderFilters:
    page: int = 1
    page_size: int = 20
    customer_id: UUID | None = None
    status: OrderStatus | None = None
