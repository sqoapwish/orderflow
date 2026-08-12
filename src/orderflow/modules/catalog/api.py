from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.catalog.dependencies import get_catalog_service
from orderflow.modules.catalog.domain import ProductFilters, ProductSortField, SortDirection
from orderflow.modules.catalog.schemas import (
    CategoryCreateRequest,
    CategoryListResponse,
    CategoryResponse,
    CategoryUpdateRequest,
    ProductCreateRequest,
    ProductPageResponse,
    ProductResponse,
    ProductUpdateRequest,
)
from orderflow.modules.catalog.service import CatalogService

router = APIRouter()

CatalogServiceDependency = Annotated[CatalogService, Depends(get_catalog_service)]
CatalogWriterDependency = Annotated[
    User,
    Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN)),
]


@router.get("/categories", response_model=CategoryListResponse, summary="List active categories")
async def list_categories(service: CatalogServiceDependency) -> CategoryListResponse:
    categories = await service.list_public_categories()
    return CategoryListResponse(
        items=[CategoryResponse.model_validate(category) for category in categories],
        total=len(categories),
    )


@router.get(
    "/categories/{slug}",
    response_model=CategoryResponse,
    summary="Get an active category by slug",
)
async def get_category(slug: str, service: CatalogServiceDependency) -> CategoryResponse:
    return CategoryResponse.model_validate(await service.get_public_category(slug))


@router.post(
    "/categories",
    response_model=CategoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a category",
)
async def create_category(
    payload: CategoryCreateRequest,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> CategoryResponse:
    category = await service.create_category(
        name=payload.name,
        slug=payload.slug,
        parent_id=payload.parent_id,
        is_active=payload.is_active,
    )
    return CategoryResponse.model_validate(category)


@router.patch(
    "/categories/id/{category_id}",
    response_model=CategoryResponse,
    summary="Update a category",
)
async def update_category(
    category_id: UUID,
    payload: CategoryUpdateRequest,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> CategoryResponse:
    category = await service.update_category(category_id, payload.to_fields())
    return CategoryResponse.model_validate(category)


@router.delete(
    "/categories/id/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a category",
)
async def archive_category(
    category_id: UUID,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> Response:
    await service.archive_category(category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products", response_model=ProductPageResponse, summary="Search active products")
async def list_products(
    service: CatalogServiceDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: Annotated[str | None, Query(min_length=1, max_length=200, pattern=r"\S")] = None,
    category_id: UUID | None = None,
    min_price_minor: Annotated[int | None, Query(ge=0)] = None,
    max_price_minor: Annotated[int | None, Query(ge=0)] = None,
    sort_by: ProductSortField = ProductSortField.CREATED_AT,
    sort_direction: SortDirection = SortDirection.DESC,
) -> ProductPageResponse:
    result = await service.list_public_products(
        ProductFilters(
            page=page,
            page_size=page_size,
            search=search.strip() if search else None,
            category_id=category_id,
            min_price_minor=min_price_minor,
            max_price_minor=max_price_minor,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )
    )
    return ProductPageResponse(
        items=[ProductResponse.model_validate(product) for product in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/products/{slug}",
    response_model=ProductResponse,
    summary="Get an active product by slug",
)
async def get_product(slug: str, service: CatalogServiceDependency) -> ProductResponse:
    return ProductResponse.model_validate(await service.get_public_product(slug))


@router.post(
    "/products",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a product",
)
async def create_product(
    payload: ProductCreateRequest,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> ProductResponse:
    product = await service.create_product(
        category_id=payload.category_id,
        name=payload.name,
        slug=payload.slug,
        sku=payload.sku,
        description=payload.description,
        price_minor=payload.price_minor,
        currency=payload.currency,
        image_url=str(payload.image_url) if payload.image_url is not None else None,
        is_active=payload.is_active,
    )
    return ProductResponse.model_validate(product)


@router.patch(
    "/products/id/{product_id}",
    response_model=ProductResponse,
    summary="Update a product",
)
async def update_product(
    product_id: UUID,
    payload: ProductUpdateRequest,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> ProductResponse:
    product = await service.update_product(product_id, payload.to_fields())
    return ProductResponse.model_validate(product)


@router.delete(
    "/products/id/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a product",
)
async def archive_product(
    product_id: UUID,
    service: CatalogServiceDependency,
    _: CatalogWriterDependency,
) -> Response:
    await service.archive_product(product_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
