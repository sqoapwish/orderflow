from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from orderflow.modules.catalog.domain import ProductFilters, ProductSortField, SortDirection
from orderflow.modules.catalog.errors import (
    CatalogWriteConflictError,
    CategoryCycleError,
    CategoryNotEmptyError,
    CategoryNotFoundError,
    CategorySlugConflictError,
    InactiveParentCategoryError,
    InactiveProductCategoryError,
    InvalidPriceRangeError,
    ProductNotFoundError,
    ProductSkuConflictError,
    ProductSlugConflictError,
)
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.catalog.service import CatalogService
from tests.fakes import FakeCatalogRepository, build_catalog_service


async def create_category(
    service: CatalogService,
    *,
    name: str = "Electronics",
    slug: str = "electronics",
    parent_id: UUID | None = None,
    is_active: bool = True,
) -> Category:
    return await service.create_category(
        name=name,
        slug=slug,
        parent_id=parent_id,
        is_active=is_active,
    )


async def create_product(
    service: CatalogService,
    category: Category,
    *,
    name: str = "Laptop Pro",
    slug: str = "laptop-pro",
    sku: str = "LAPTOP-PRO",
    price_minor: int = 199_900,
    is_active: bool = True,
) -> Product:
    return await service.create_product(
        category_id=category.id,
        name=name,
        slug=slug,
        sku=sku,
        description="A test product",
        price_minor=price_minor,
        currency="RUB",
        image_url="https://example.com/product.jpg",
        is_active=is_active,
    )


async def test_nested_categories_reject_self_and_descendant_cycles() -> None:
    service, repository = build_catalog_service()
    root = await create_category(service)
    child = await create_category(
        service,
        name="Computers",
        slug="computers",
        parent_id=root.id,
    )
    grandchild = await create_category(
        service,
        name="Laptops",
        slug="laptops",
        parent_id=child.id,
    )

    with pytest.raises(CategoryCycleError):
        await service.update_category(root.id, {"parent_id": root.id})
    with pytest.raises(CategoryCycleError):
        await service.update_category(root.id, {"parent_id": grandchild.id})

    assert repository.catalog_write_locks == 5


async def test_active_category_requires_active_parent() -> None:
    service, _ = build_catalog_service()
    parent = await create_category(service, is_active=False)

    with pytest.raises(InactiveParentCategoryError):
        await create_category(
            service,
            name="Computers",
            slug="computers",
            parent_id=parent.id,
        )

    child = await create_category(
        service,
        name="Computers",
        slug="computers",
        parent_id=parent.id,
        is_active=False,
    )
    with pytest.raises(InactiveParentCategoryError):
        await service.update_category(child.id, {"is_active": True})


async def test_category_archive_requires_empty_active_branch() -> None:
    service, repository = build_catalog_service()
    parent = await create_category(service)
    child = await create_category(
        service,
        name="Computers",
        slug="computers",
        parent_id=parent.id,
    )

    with pytest.raises(CategoryNotEmptyError):
        await service.archive_category(parent.id)

    await service.archive_category(child.id)
    await service.archive_category(parent.id)
    await service.archive_category(parent.id)

    assert repository.categories[parent.id].is_active is False


async def test_category_slug_conflict_and_missing_category_are_explicit() -> None:
    service, _ = build_catalog_service()
    category = await create_category(service)

    with pytest.raises(CategorySlugConflictError):
        await create_category(service, name="Other", slug=category.slug)
    with pytest.raises(CategoryNotFoundError):
        await service.get_public_category("missing")
    with pytest.raises(CategoryNotFoundError):
        await service.update_category(uuid4(), {"name": "Missing"})


async def test_product_identity_category_and_archive_rules() -> None:
    service, _ = build_catalog_service()
    category = await create_category(service)
    inactive_category = await create_category(
        service,
        name="Drafts",
        slug="drafts",
        is_active=False,
    )
    product = await create_product(service, category)

    with pytest.raises(ProductSlugConflictError):
        await create_product(service, category, name="Other", slug=product.slug, sku="OTHER")
    with pytest.raises(ProductSkuConflictError):
        await create_product(service, category, name="Other", slug="other", sku=product.sku)
    with pytest.raises(InactiveProductCategoryError):
        await create_product(
            service,
            inactive_category,
            name="Hidden",
            slug="hidden",
            sku="HIDDEN",
        )

    draft = await create_product(
        service,
        inactive_category,
        name="Hidden",
        slug="hidden",
        sku="HIDDEN",
        is_active=False,
    )
    with pytest.raises(InactiveProductCategoryError):
        await service.update_product(draft.id, {"is_active": True})

    await service.update_product(product.id, {"price_minor": 179_900, "sku": "NEW-SKU"})
    await service.archive_product(product.id)
    await service.archive_product(product.id)

    with pytest.raises(ProductNotFoundError):
        await service.get_public_product(product.slug)
    with pytest.raises(ProductNotFoundError):
        await service.update_product(uuid4(), {"name": "Missing"})


async def test_public_product_search_filter_sort_and_pagination() -> None:
    service, _ = build_catalog_service()
    laptops = await create_category(service, name="Laptops", slug="laptops")
    phones = await create_category(service, name="Phones", slug="phones")
    await create_product(
        service,
        laptops,
        name="Laptop Air",
        slug="laptop-air",
        sku="AIR-13",
        price_minor=99_900,
    )
    await create_product(
        service,
        laptops,
        name="Laptop Pro",
        slug="laptop-pro",
        sku="PRO-16",
        price_minor=199_900,
    )
    await create_product(
        service,
        phones,
        name="Phone",
        slug="phone",
        sku="PHONE-1",
        price_minor=69_900,
    )

    page = await service.list_public_products(
        ProductFilters(
            page=1,
            page_size=1,
            search="laptop",
            category_id=laptops.id,
            min_price_minor=90_000,
            max_price_minor=200_000,
            sort_by=ProductSortField.PRICE,
            sort_direction=SortDirection.DESC,
        )
    )

    assert [product.sku for product in page.items] == ["PRO-16"]
    assert page.total == 2
    assert page.total_pages == 2

    with pytest.raises(InvalidPriceRangeError):
        await service.list_public_products(
            ProductFilters(min_price_minor=200_000, max_price_minor=100_000)
        )


async def test_public_catalog_hides_archived_category_and_products() -> None:
    service, _ = build_catalog_service()
    category = await create_category(service)
    active = await create_product(service, category)
    await create_product(
        service,
        category,
        name="Draft",
        slug="draft",
        sku="DRAFT",
        is_active=False,
    )

    products = await service.list_public_products(ProductFilters())
    assert [product.id for product in products.items] == [active.id]

    await service.archive_product(active.id)
    await service.archive_category(category.id)
    assert await service.list_public_categories() == []
    assert (await service.list_public_products(ProductFilters())).items == []


async def test_integrity_error_rolls_back_and_uses_stable_conflict() -> None:
    class FailingRepository(FakeCatalogRepository):
        async def flush(self) -> None:
            raise IntegrityError("insert", {}, Exception("unique race"))

    repository = FailingRepository()
    service = CatalogService(repository)

    with pytest.raises(CatalogWriteConflictError):
        await create_category(service)

    assert repository.rollbacks == 1
