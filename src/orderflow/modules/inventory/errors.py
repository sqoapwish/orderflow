from fastapi import status

from orderflow.core.errors import ApplicationError


class WarehouseNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="warehouse_not_found",
            message="Warehouse was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class WarehouseCodeConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="warehouse_code_conflict",
            message="A warehouse with this code already exists",
            status_code=status.HTTP_409_CONFLICT,
        )


class InactiveWarehouseError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="inactive_warehouse",
            message="Inventory operations require an active warehouse",
            status_code=status.HTTP_409_CONFLICT,
        )


class WarehouseNotEmptyError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="warehouse_not_empty",
            message="A warehouse with stock or reservations cannot be archived",
            status_code=status.HTTP_409_CONFLICT,
        )


class InsufficientAvailableStockError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="insufficient_available_stock",
            message="The warehouse does not have enough available stock",
            status_code=status.HTTP_409_CONFLICT,
        )


class AdjustmentBelowReservedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="adjustment_below_reserved",
            message="Physical stock cannot be adjusted below the reserved quantity",
            status_code=status.HTTP_409_CONFLICT,
        )


class NoStockChangeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="no_stock_change",
            message="The requested adjustment does not change physical stock",
            status_code=status.HTTP_409_CONFLICT,
        )


class ReservationNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="reservation_not_found",
            message="Inventory reservation was not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ReservationKeyConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="reservation_key_conflict",
            message="Reservation key is already used for different stock",
            status_code=status.HTTP_409_CONFLICT,
        )


class ReservationStateConflictError(ApplicationError):
    def __init__(self, *, target: str) -> None:
        super().__init__(
            code="reservation_state_conflict",
            message=f"Reservation cannot be {target} from its current state",
            status_code=status.HTTP_409_CONFLICT,
        )


class InventoryWriteConflictError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="inventory_write_conflict",
            message="Inventory data conflicts with a concurrent or existing record",
            status_code=status.HTTP_409_CONFLICT,
        )
