from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class ProductSortField(StrEnum):
    CREATED_AT = "created_at"
    NAME = "name"
    PRICE = "price"


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class CategoryUpdateFields(TypedDict, total=False):
    name: str
    slug: str
    parent_id: UUID | None
    is_active: bool


class ProductUpdateFields(TypedDict, total=False):
    category_id: UUID
    name: str
    slug: str
    sku: str
    description: str | None
    price_minor: int
    currency: str
    image_url: str | None
    is_active: bool


@dataclass(frozen=True, slots=True)
class ProductFilters:
    page: int = 1
    page_size: int = 20
    search: str | None = None
    category_id: UUID | None = None
    min_price_minor: int | None = None
    max_price_minor: int | None = None
    sort_by: ProductSortField = ProductSortField.CREATED_AT
    sort_direction: SortDirection = SortDirection.DESC
