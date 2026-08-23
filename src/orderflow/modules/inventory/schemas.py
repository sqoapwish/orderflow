from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orderflow.modules.inventory.domain import (
    InventoryMovementType,
    ReservationStatus,
    WarehouseUpdateFields,
)

WAREHOUSE_CODE_PATTERN = r"^[A-Z0-9][A-Z0-9_-]*$"
RESERVATION_KEY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
MAX_QUANTITY = 9_999_999_999_999


class InventoryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class WarehouseCreateRequest(InventoryRequest):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=2, max_length=32, pattern=WAREHOUSE_CODE_PATTERN)
    location: str | None = Field(default=None, max_length=255)
    is_active: bool = True

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class WarehouseUpdateRequest(InventoryRequest):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    code: str | None = Field(
        default=None,
        min_length=2,
        max_length=32,
        pattern=WAREHOUSE_CODE_PATTERN,
    )
    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one warehouse field must be provided")
        for field_name in self.model_fields_set - {"location"}:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    def to_fields(self) -> WarehouseUpdateFields:
        fields = WarehouseUpdateFields()
        if "name" in self.model_fields_set:
            assert self.name is not None
            fields["name"] = self.name
        if "code" in self.model_fields_set:
            assert self.code is not None
            fields["code"] = self.code
        if "location" in self.model_fields_set:
            fields["location"] = self.location
        if "is_active" in self.model_fields_set:
            assert self.is_active is not None
            fields["is_active"] = self.is_active
        return fields


class StockOperationRequest(InventoryRequest):
    warehouse_id: UUID
    product_id: UUID
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class StockAdjustmentRequest(InventoryRequest):
    warehouse_id: UUID
    product_id: UUID
    on_hand: int = Field(ge=0, le=MAX_QUANTITY)
    reason: str = Field(min_length=3, max_length=500)


class StockTransferRequest(InventoryRequest):
    source_warehouse_id: UUID
    target_warehouse_id: UUID
    product_id: UUID
    quantity: int = Field(gt=0, le=MAX_QUANTITY)
    reason: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_warehouses(self) -> Self:
        if self.source_warehouse_id == self.target_warehouse_id:
            raise ValueError("Source and target warehouses must be different")
        return self


class ReservationCreateRequest(InventoryRequest):
    reservation_key: str = Field(
        min_length=1,
        max_length=128,
        pattern=RESERVATION_KEY_PATTERN,
    )
    warehouse_id: UUID
    product_id: UUID
    quantity: int = Field(gt=0, le=MAX_QUANTITY)


class WarehouseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    location: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WarehouseListResponse(BaseModel):
    items: list[WarehouseResponse]
    total: int


class ProductAvailabilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    warehouse_id: UUID
    warehouse_name: str
    warehouse_code: str
    available: int


class ProductAvailabilityListResponse(BaseModel):
    items: list[ProductAvailabilityResponse]
    total: int


class StockBalanceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    warehouse_id: UUID
    product_id: UUID
    on_hand: int
    reserved: int
    available: int
    created_at: datetime
    updated_at: datetime


class StockPageResponse(BaseModel):
    items: list[StockBalanceResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StockMutationResponse(BaseModel):
    operation_id: UUID
    balance: StockBalanceResponse


class StockTransferResponse(BaseModel):
    operation_id: UUID
    source: StockBalanceResponse
    target: StockBalanceResponse


class InventoryMovementResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    operation_id: UUID
    warehouse_id: UUID
    product_id: UUID
    reservation_id: UUID | None
    movement_type: InventoryMovementType
    delta_on_hand: int
    delta_reserved: int
    balance_on_hand: int
    balance_reserved: int
    reason: str | None
    created_by_user_id: UUID
    created_at: datetime


class MovementPageResponse(BaseModel):
    items: list[InventoryMovementResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ReservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reservation_key: str
    warehouse_id: UUID
    product_id: UUID
    quantity: int
    status: ReservationStatus
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime
