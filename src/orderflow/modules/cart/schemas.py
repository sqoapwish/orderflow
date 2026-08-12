from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orderflow.modules.cart.service import MAX_CART_ITEM_QUANTITY


class CartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CartItemCreateRequest(CartRequest):
    product_id: UUID
    warehouse_id: UUID
    quantity: int = Field(gt=0, le=MAX_CART_ITEM_QUANTITY)


class CartItemUpdateRequest(CartRequest):
    quantity: int = Field(gt=0, le=MAX_CART_ITEM_QUANTITY)


class CartItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    warehouse_id: UUID
    product_name: str
    product_sku: str
    unit_price_minor: int
    quantity: int
    line_total_minor: int
    currency: str
    is_available: bool
    created_at: datetime
    updated_at: datetime


class CartResponse(BaseModel):
    id: UUID | None
    items: list[CartItemResponse]
    total_minor: int | None
    currency: str | None
    updated_at: datetime | None
