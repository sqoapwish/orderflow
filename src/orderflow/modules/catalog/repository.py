from collections.abc import Iterable
from typing import Protocol
from uuid import UUID

from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from orderflow.modules.catalog.domain import ProductFilters, ProductSortField, SortDirection
from orderflow.modules.catalog.models import Category, Product

CATALOG_WRITE_LOCK_ID = 202608120003


class CatalogRepositoryProtocol(Protocol):
    async def acquire_catalog_write_lock(self) -> None: ...

    async def list_public_categories(self) -> list[Category]: ...

    async def get_category(self, category_id: UUID) -> Category | None: ...

    async def get_public_category_by_slug(self, slug: str) -> Category | None: ...

    async def category_slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool: ...

    async def is_category_descendant(self, category_id: UUID, candidate_id: UUID) -> bool: ...

    async def category_has_active_dependencies(self, category_id: UUID) -> bool: ...

    def add_category(self, category: Category) -> None: ...

    async def get_product(self, product_id: UUID) -> Product | None: ...

    async def get_products_with_category_state(
        self,
        product_ids: Iterable[UUID],
    ) -> list[tuple[Product, bool]]: ...

    async def get_public_product_by_slug(self, slug: str) -> Product | None: ...

    async def list_public_products(self, filters: ProductFilters) -> tuple[list[Product], int]: ...

    async def product_slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool: ...

    async def product_sku_exists(self, sku: str, exclude_id: UUID | None = None) -> bool: ...

    def add_product(self, product: Product) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class CatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def acquire_catalog_write_lock(self) -> None:
        # Catalog mutations are rare. A transaction-level lock preserves tree and
        # active-category invariants across concurrent requests.
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": CATALOG_WRITE_LOCK_ID},
        )

    async def list_public_categories(self) -> list[Category]:
        statement = select(Category).where(Category.is_active.is_(True)).order_by(Category.name)
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_category(self, category_id: UUID) -> Category | None:
        return await self._session.get(Category, category_id)

    async def get_public_category_by_slug(self, slug: str) -> Category | None:
        statement = select(Category).where(Category.slug == slug, Category.is_active.is_(True))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def category_slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool:
        conditions: list[ColumnElement[bool]] = [Category.slug == slug]
        if exclude_id is not None:
            conditions.append(Category.id != exclude_id)
        statement = select(exists().where(*conditions))
        return bool(await self._session.scalar(statement))

    async def is_category_descendant(self, category_id: UUID, candidate_id: UUID) -> bool:
        descendants = (
            select(Category.id)
            .where(Category.parent_id == category_id)
            .cte(name="category_descendants", recursive=True)
        )
        descendants = descendants.union_all(
            select(Category.id).where(Category.parent_id == descendants.c.id)
        )
        statement = select(exists().where(descendants.c.id == candidate_id))
        return bool(await self._session.scalar(statement))

    async def category_has_active_dependencies(self, category_id: UUID) -> bool:
        active_child = await self._session.scalar(
            select(
                exists().where(
                    Category.parent_id == category_id,
                    Category.is_active.is_(True),
                )
            )
        )
        if active_child:
            return True
        active_product = await self._session.scalar(
            select(
                exists().where(
                    Product.category_id == category_id,
                    Product.is_active.is_(True),
                )
            )
        )
        return bool(active_product)

    def add_category(self, category: Category) -> None:
        self._session.add(category)

    async def get_product(self, product_id: UUID) -> Product | None:
        return await self._session.get(Product, product_id)

    async def get_products_with_category_state(
        self,
        product_ids: Iterable[UUID],
    ) -> list[tuple[Product, bool]]:
        ordered_ids = sorted(set(product_ids), key=lambda product_id: product_id.int)
        if not ordered_ids:
            return []
        statement = (
            select(Product, Category.is_active)
            .join(Category, Category.id == Product.category_id)
            .where(Product.id.in_(ordered_ids))
            .order_by(Product.id)
        )
        result = await self._session.execute(statement)
        return [(product, category_is_active) for product, category_is_active in result.all()]

    async def get_public_product_by_slug(self, slug: str) -> Product | None:
        statement = (
            select(Product)
            .join(Category, Product.category_id == Category.id)
            .where(
                Product.slug == slug,
                Product.is_active.is_(True),
                Category.is_active.is_(True),
            )
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_public_products(self, filters: ProductFilters) -> tuple[list[Product], int]:
        conditions: list[ColumnElement[bool]] = [
            Product.is_active.is_(True),
            Category.is_active.is_(True),
        ]
        if filters.search:
            conditions.append(
                or_(
                    Product.name.icontains(filters.search, autoescape=True),
                    Product.sku.icontains(filters.search, autoescape=True),
                )
            )
        if filters.category_id is not None:
            conditions.append(Product.category_id == filters.category_id)
        if filters.min_price_minor is not None:
            conditions.append(Product.price_minor >= filters.min_price_minor)
        if filters.max_price_minor is not None:
            conditions.append(Product.price_minor <= filters.max_price_minor)

        total_statement = (
            select(func.count()).select_from(Product).join(Category).where(*conditions)
        )
        total = int((await self._session.scalar(total_statement)) or 0)

        sort_column = {
            ProductSortField.CREATED_AT: Product.created_at,
            ProductSortField.NAME: Product.name,
            ProductSortField.PRICE: Product.price_minor,
        }[filters.sort_by]
        sort_expression = (
            sort_column.asc() if filters.sort_direction is SortDirection.ASC else sort_column.desc()
        )
        statement = (
            select(Product)
            .join(Category)
            .where(*conditions)
            .order_by(sort_expression, Product.id.asc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def product_slug_exists(self, slug: str, exclude_id: UUID | None = None) -> bool:
        conditions: list[ColumnElement[bool]] = [Product.slug == slug]
        if exclude_id is not None:
            conditions.append(Product.id != exclude_id)
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    async def product_sku_exists(self, sku: str, exclude_id: UUID | None = None) -> bool:
        conditions: list[ColumnElement[bool]] = [Product.sku == sku]
        if exclude_id is not None:
            conditions.append(Product.id != exclude_id)
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    def add_product(self, product: Product) -> None:
        self._session.add(product)

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
