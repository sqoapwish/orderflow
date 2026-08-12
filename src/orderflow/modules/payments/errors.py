from fastapi import status

from orderflow.core.errors import ApplicationError


class PaymentNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="payment_not_found",
            message="Payment was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidPaymentIdempotencyKeyError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_payment_idempotency_key",
            message="Idempotency-Key must contain between 1 and 128 non-whitespace characters",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class PaymentIdempotencyConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="payment_idempotency_conflict",
            message="Idempotency-Key is already associated with another payment operation",
            status_code=status.HTTP_409_CONFLICT,
        )


class PaymentStateConflictError(ApplicationError):
    def __init__(self, *, current: str, operation: str) -> None:
        super().__init__(
            code="payment_state_conflict",
            message=f"Payment in state '{current}' cannot be used to {operation}",
            status_code=status.HTTP_409_CONFLICT,
        )


class PaymentAmountConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="payment_amount_conflict",
            message="Webhook amount or currency does not match the payment",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidWebhookSignatureError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_webhook_signature",
            message="Payment webhook signature is invalid",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class StaleWebhookError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="stale_webhook",
            message="Payment webhook timestamp is outside the allowed tolerance",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class InvalidWebhookPayloadError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_webhook_payload",
            message="Payment webhook payload failed validation",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class WebhookEventConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="webhook_event_conflict",
            message="Webhook event identifier was reused with a different payload",
            status_code=status.HTTP_409_CONFLICT,
        )


class PaymentWriteConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="payment_write_conflict",
            message="Payment data conflicts with a concurrent or existing record",
            status_code=status.HTTP_409_CONFLICT,
        )
