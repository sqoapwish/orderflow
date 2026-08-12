from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from orderflow.modules.catalog.domain import CategoryUpdateFields, ProductUpdateFields

SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SKU_PATTERN = r"^[A-Z0-9][A-Z0-9._-]*$"


class CatalogRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class CategoryCreateRequest(CatalogRequest):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=120, pattern=SLUG_PATTERN)
    parent_id: UUID | None = None
    is_active: bool = True


class CategoryUpdateRequest(CatalogRequest):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    slug: str | None = Field(default=None, min_length=2, max_length=120, pattern=SLUG_PATTERN)
    parent_id: UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one category field must be provided")
        for field_name in ("name", "slug", "is_active"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    def to_fields(self) -> CategoryUpdateFields:
        fields = CategoryUpdateFields()
        if "name" in self.model_fields_set:
            assert self.name is not None
            fields["name"] = self.name
        if "slug" in self.model_fields_set:
            assert self.slug is not None
            fields["slug"] = self.slug
        if "parent_id" in self.model_fields_set:
            fields["parent_id"] = self.parent_id
        if "is_active" in self.model_fields_set:
            assert self.is_active is not None
            fields["is_active"] = self.is_active
        return fields


class ProductCreateRequest(CatalogRequest):
    category_id: UUID
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=200, pattern=SLUG_PATTERN)
    sku: str = Field(min_length=1, max_length=64, pattern=SKU_PATTERN)
    description: str | None = Field(default=None, max_length=5000)
    price_minor: int = Field(gt=0, le=9_999_999_999_999)
    currency: str = Field(default="RUB", min_length=3, max_length=3)
    image_url: HttpUrl | None = Field(default=None, max_length=2048)
    is_active: bool = True

    @field_validator("sku", mode="before")
    @classmethod
    def normalize_sku(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class ProductUpdateRequest(CatalogRequest):
    category_id: UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    slug: str | None = Field(default=None, min_length=2, max_length=200, pattern=SLUG_PATTERN)
    sku: str | None = Field(default=None, min_length=1, max_length=64, pattern=SKU_PATTERN)
    description: str | None = Field(default=None, max_length=5000)
    price_minor: int | None = Field(default=None, gt=0, le=9_999_999_999_999)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    image_url: HttpUrl | None = Field(default=None, max_length=2048)
    is_active: bool | None = None

    @field_validator("sku", mode="before")
    @classmethod
    def normalize_sku(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one product field must be provided")
        nullable_fields = {"description", "image_url"}
        for field_name in self.model_fields_set - nullable_fields:
            if getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self

    def to_fields(self) -> ProductUpdateFields:
        fields = ProductUpdateFields()
        for field_name in self.model_fields_set:
            value = getattr(self, field_name)
            if field_name == "image_url":
                fields["image_url"] = str(value) if value is not None else None
            elif field_name == "category_id":
                assert isinstance(value, UUID)
                fields["category_id"] = value
            elif field_name in {"name", "slug", "sku", "currency"}:
                assert isinstance(value, str)
                fields[field_name] = value  # type: ignore[literal-required]
            elif field_name == "description":
                assert value is None or isinstance(value, str)
                fields["description"] = value
            elif field_name == "price_minor":
                assert isinstance(value, int)
                fields["price_minor"] = value
            elif field_name == "is_active":
                assert isinstance(value, bool)
                fields["is_active"] = value
        return fields


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    parent_id: UUID | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryListResponse(BaseModel):
    items: list[CategoryResponse]
    total: int


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    category_id: UUID
    name: str
    slug: str
    sku: str
    description: str | None
    price_minor: int
    currency: str
    image_url: HttpUrl | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductPageResponse(BaseModel):
    items: list[ProductResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
