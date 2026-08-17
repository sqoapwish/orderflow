from enum import StrEnum


class OutboxEventType(StrEnum):
    ORDER_CREATED = "order.created"
    ORDER_CANCELLED = "order.cancelled"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_REFUNDED = "payment.refunded"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    DEAD_LETTER = "dead_letter"


class InboxOutcome(StrEnum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
