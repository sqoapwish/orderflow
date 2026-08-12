from dataclasses import dataclass
from math import ceil
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from orderflow.modules.catalog.domain import (
    CategoryUpdateFields,
    ProductFilters,
    ProductUpdateFields,
)
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
from orderflow.modules.catalog.repository import CatalogRepositoryProtocol


@dataclass(frozen=True, slots=True)
class ProductDescriptor:
    product: Product
    is_available: bool


@dataclass(frozen=True, slots=True)
class ProductPage:
    items: list[Product]
    total: int
    page: int
    page_size: int
    total_pages: int


class CatalogService:
    def __init__(self, repository: CatalogRepositoryProtocol) -> None:
        self._repository = repository

    async def list_public_categories(self) -> list[Category]:
        return await self._repository.list_public_categories()

    async def get_public_category(self, slug: str) -> Category:
        category = await self._repository.get_public_category_by_slug(slug)
        if category is None:
            raise CategoryNotFoundError
        return category

    async def create_category(
        self,
        *,
        name: str,
        slug: str,
        parent_id: UUID | None,
        is_active: bool,
    ) -> Category:
        await self._repository.acquire_catalog_write_lock()
        if await self._repository.category_slug_exists(slug):
            raise CategorySlugConflictError
        if parent_id is not None:
            parent = await self._require_category(parent_id)
            if is_active and not parent.is_active:
                raise InactiveParentCategoryError

        category = Category(name=name, slug=slug, parent_id=parent_id, is_active=is_active)
        self._repository.add_category(category)
        await self._save()
        return category

    async def update_category(
        self,
        category_id: UUID,
        fields: CategoryUpdateFields,
    ) -> Category:
        await self._repository.acquire_catalog_write_lock()
        category = await self._require_category(category_id)
        if (
            "slug" in fields
            and fields["slug"] != category.slug
            and await self._repository.category_slug_exists(fields["slug"], category.id)
        ):
            raise CategorySlugConflictError

        target_parent_id = fields.get("parent_id", category.parent_id)
        target_is_active = fields.get("is_active", category.is_active)
        if target_parent_id is not None:
            if target_parent_id == category.id:
                raise CategoryCycleError
            parent = await self._require_category(target_parent_id)
            if await self._repository.is_category_descendant(category.id, parent.id):
                raise CategoryCycleError
            if target_is_active and not parent.is_active:
                raise InactiveParentCategoryError

        if (
            category.is_active
            and not target_is_active
            and await self._repository.category_has_active_dependencies(category.id)
        ):
            raise CategoryNotEmptyError

        for field_name, value in fields.items():
            setattr(category, field_name, value)
        await self._save()
        return category

    async def archive_category(self, category_id: UUID) -> None:
        await self._repository.acquire_catalog_write_lock()
        category = await self._require_category(category_id)
        if not category.is_active:
            return
        if await self._repository.category_has_active_dependencies(category.id):
            raise CategoryNotEmptyError
        category.is_active = False
        await self._save()

    async def list_public_products(self, filters: ProductFilters) -> ProductPage:
        if (
            filters.min_price_minor is not None
            and filters.max_price_minor is not None
            and filters.min_price_minor > filters.max_price_minor
        ):
            raise InvalidPriceRangeError
        products, total = await self._repository.list_public_products(filters)
        return ProductPage(
            items=products,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def get_public_product(self, slug: str) -> Product:
        product = await self._repository.get_public_product_by_slug(slug)
        if product is None:
            raise ProductNotFoundError
        return product

    async def require_active_product_for_inventory(self, product_id: UUID) -> None:
        product = await self._repository.get_product(product_id)
        if product is None or not product.is_active:
            raise ProductNotFoundError
        category = await self._repository.get_category(product.category_id)
        if category is None or not category.is_active:
            raise ProductNotFoundError

    async def require_product_for_inventory(self, product_id: UUID) -> None:
        if await self._repository.get_product(product_id) is None:
            raise ProductNotFoundError

    async def describe_products(
        self,
        product_ids: list[UUID],
    ) -> dict[UUID, ProductDescriptor]:
        records = await self._repository.get_products_with_category_state(product_ids)
        return {
            product.id: ProductDescriptor(
                product=product,
                is_available=product.is_active and category_is_active,
            )
            for product, category_is_active in records
        }

    async def lock_orderable_products(self, product_ids: list[UUID]) -> dict[UUID, Product]:
        expected = set(product_ids)
        await self._repository.acquire_catalog_write_lock()
        descriptors = await self.describe_products(list(expected))
        if set(descriptors) != expected or any(
            not descriptor.is_available for descriptor in descriptors.values()
        ):
            raise ProductNotFoundError
        return {product_id: descriptor.product for product_id, descriptor in descriptors.items()}

    async def create_product(
        self,
        *,
        category_id: UUID,
        name: str,
        slug: str,
        sku: str,
        description: str | None,
        price_minor: int,
        currency: str,
        image_url: str | None,
        is_active: bool,
    ) -> Product:
        await self._repository.acquire_catalog_write_lock()
        category = await self._require_category(category_id)
        if is_active and not category.is_active:
            raise InactiveProductCategoryError
        await self._ensure_product_identity_available(slug=slug, sku=sku)
        product = Product(
            category_id=category_id,
            name=name,
            slug=slug,
            sku=sku,
            description=description,
            price_minor=price_minor,
            currency=currency,
            image_url=image_url,
            is_active=is_active,
        )
        self._repository.add_product(product)
        await self._save()
        return product

    async def update_product(
        self,
        product_id: UUID,
        fields: ProductUpdateFields,
    ) -> Product:
        await self._repository.acquire_catalog_write_lock()
        product = await self._require_product(product_id)
        if (
            "slug" in fields
            and fields["slug"] != product.slug
            and await self._repository.product_slug_exists(fields["slug"], product.id)
        ):
            raise ProductSlugConflictError
        if (
            "sku" in fields
            and fields["sku"] != product.sku
            and await self._repository.product_sku_exists(fields["sku"], product.id)
        ):
            raise ProductSkuConflictError

        target_category_id = fields.get("category_id", product.category_id)
        target_is_active = fields.get("is_active", product.is_active)
        category = await self._require_category(target_category_id)
        if target_is_active and not category.is_active:
            raise InactiveProductCategoryError

        for field_name, value in fields.items():
            setattr(product, field_name, value)
        await self._save()
        return product

    async def archive_product(self, product_id: UUID) -> None:
        await self._repository.acquire_catalog_write_lock()
        product = await self._require_product(product_id)
        if not product.is_active:
            return
        product.is_active = False
        await self._save()

    async def _require_category(self, category_id: UUID) -> Category:
        category = await self._repository.get_category(category_id)
        if category is None:
            raise CategoryNotFoundError
        return category

    async def _require_product(self, product_id: UUID) -> Product:
        product = await self._repository.get_product(product_id)
        if product is None:
            raise ProductNotFoundError
        return product

    async def _ensure_product_identity_available(self, *, slug: str, sku: str) -> None:
        if await self._repository.product_slug_exists(slug):
            raise ProductSlugConflictError
        if await self._repository.product_sku_exists(sku):
            raise ProductSkuConflictError

    async def _save(self) -> None:
        try:
            await self._repository.flush()
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            raise CatalogWriteConflictError from None
