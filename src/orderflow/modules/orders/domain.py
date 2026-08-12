from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class OrderStatus(StrEnum):
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


ORDER_STATUS_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.PENDING_PAYMENT: frozenset(
        {OrderStatus.PAID, OrderStatus.PAYMENT_FAILED, OrderStatus.CANCELLED}
    ),
    OrderStatus.PAID: frozenset({OrderStatus.REFUNDED}),
    OrderStatus.PAYMENT_FAILED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REFUNDED: frozenset(),
}


def can_transition_order(current: OrderStatus, target: OrderStatus) -> bool:
    return target in ORDER_STATUS_TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class OrderFilters:
    page: int = 1
    page_size: int = 20
    customer_id: UUID | None = None
    status: OrderStatus | None = None
