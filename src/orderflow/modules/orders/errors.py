from fastapi import status

from orderflow.core.errors import ApplicationError


class OrderNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="order_not_found",
            message="Order was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class OrderTotalOverflowError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="order_total_overflow",
            message="Order total exceeds the supported monetary range",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidIdempotencyKeyError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="invalid_idempotency_key",
            message="Idempotency-Key must contain between 1 and 128 non-whitespace characters",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class OrderWriteConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="order_write_conflict",
            message="Order data conflicts with a concurrent or existing record",
            status_code=status.HTTP_409_CONFLICT,
        )


class OrderStateConflictError(ApplicationError):
    def __init__(self, *, current: str, target: str) -> None:
        super().__init__(
            code="order_state_conflict",
            message=f"Order cannot transition from '{current}' to '{target}'",
            status_code=status.HTTP_409_CONFLICT,
        )
