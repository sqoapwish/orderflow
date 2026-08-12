from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentEventType(StrEnum):
    SUCCEEDED = "payment.succeeded"
    FAILED = "payment.failed"


class WebhookOutcome(StrEnum):
    PROCESSED = "processed"
    IGNORED = "ignored"


class RefundStatus(StrEnum):
    SUCCEEDED = "succeeded"


@dataclass(frozen=True, slots=True)
class PaymentFilters:
    page: int = 1
    page_size: int = 20
    customer_id: UUID | None = None
    status: PaymentStatus | None = None
