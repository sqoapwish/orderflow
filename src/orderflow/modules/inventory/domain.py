from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class InventoryMovementType(StrEnum):
    RECEIPT = "receipt"
    WRITE_OFF = "write_off"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    RESERVATION_CREATED = "reservation_created"
    RESERVATION_RELEASED = "reservation_released"
    RESERVATION_CONSUMED = "reservation_consumed"


class ReservationStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"
    CONSUMED = "consumed"


class WarehouseUpdateFields(TypedDict, total=False):
    name: str
    code: str
    location: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class StockFilters:
    page: int = 1
    page_size: int = 20
    warehouse_id: UUID | None = None
    product_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MovementFilters:
    page: int = 1
    page_size: int = 20
    warehouse_id: UUID | None = None
    product_id: UUID | None = None
    movement_type: InventoryMovementType | None = None
    operation_id: UUID | None = None
