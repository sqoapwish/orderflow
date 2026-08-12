from fastapi import status

from orderflow.core.errors import ApplicationError


class CartItemNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="cart_item_not_found",
            message="Cart item was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class EmptyCartError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="empty_cart",
            message="The cart is empty",
            status_code=status.HTTP_409_CONFLICT,
        )


class CartCurrencyConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="cart_currency_conflict",
            message="All cart items must use the same currency",
            status_code=status.HTTP_409_CONFLICT,
        )


class CartLimitExceededError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="cart_limit_exceeded",
            message="The cart item or quantity limit was exceeded",
            status_code=status.HTTP_409_CONFLICT,
        )


class CartWriteConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="cart_write_conflict",
            message="Cart data conflicts with a concurrent or existing record",
            status_code=status.HTTP_409_CONFLICT,
        )
