from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from argon2 import PasswordHasher

from orderflow.core.config import Settings
from orderflow.modules.auth.models import RefreshSession, User
from orderflow.modules.auth.security import PasswordService, TokenService
from orderflow.modules.auth.service import AuthService
from orderflow.modules.catalog.domain import ProductFilters, ProductSortField, SortDirection
from orderflow.modules.catalog.errors import ProductNotFoundError
from orderflow.modules.catalog.models import Category, Product
from orderflow.modules.catalog.service import CatalogService
from orderflow.modules.inventory.domain import MovementFilters, ReservationStatus, StockFilters
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)
from orderflow.modules.inventory.repository import StockKey
from orderflow.modules.inventory.service import InventoryService


class FakeAuthRepository:
    def __init__(self) -> None:
        self.users_by_email: dict[str, User] = {}
        self.users_by_id: dict[UUID, User] = {}
        self.sessions: dict[UUID, RefreshSession] = {}
        self.commits = 0
        self.rollbacks = 0

    async def get_user_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def get_user_by_id(self, user_id: UUID) -> User | None:
        return self.users_by_id.get(user_id)

    async def get_refresh_session(
        self,
        session_id: UUID,
        *,
        for_update: bool = False,
    ) -> RefreshSession | None:
        return self.sessions.get(session_id)

    def add_user(self, user: User) -> None:
        now = datetime.now(UTC)
        user.id = uuid4()
        user.is_active = True
        user.created_at = now
        user.updated_at = now
        self.users_by_email[user.email] = user
        self.users_by_id[user.id] = user

    def add_refresh_session(self, session: RefreshSession) -> None:
        self.sessions[session.id] = session

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_auth_service(
    settings: Settings,
) -> tuple[AuthService, FakeAuthRepository, PasswordService, TokenService]:
    repository = FakeAuthRepository()
    password_service = PasswordService(PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1))
    token_service = TokenService(settings)
    service = AuthService(repository, password_service, token_service)
    return service, repository, password_service, token_service


class FakeCatalogRepository:
    def __init__(self) -> None:
        self.categories: dict[UUID, Category] = {}
        self.products: dict[UUID, Product] = {}
        self.commits = 0
        self.rollbacks = 0
        self.catalog_write_locks = 0

    async def acquire_catalog_write_lock(self) -> None:
        self.catalog_write_locks += 1

    async def list_public_categories(self) -> list[Category]:
        return sorted(
            (category for category in self.categories.values() if category.is_active),
            key=lambda category: category.name,
        )

    async def get_category(self, category_id: UUID) -> Category | None:
        return self.categories.get(category_id)

    async def get_public_category_by_slug(self, slug: str) -> Category | None:
        return next(
            (
                category
                for category in self.categories.values()
                if category.slug == slug and category.is_active
            ),
            None,
        )

    async def category_slug_exists(
        self,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            category.slug == slug and category.id != exclude_id
            for category in self.categories.values()
        )

    async def is_category_descendant(self, category_id: UUID, candidate_id: UUID) -> bool:
        current = self.categories.get(candidate_id)
        seen: set[UUID] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)
            if current.parent_id == category_id:
                return True
            current = self.categories.get(current.parent_id) if current.parent_id else None
        return False

    async def category_has_active_dependencies(self, category_id: UUID) -> bool:
        return any(
            category.parent_id == category_id and category.is_active
            for category in self.categories.values()
        ) or any(
            product.category_id == category_id and product.is_active
            for product in self.products.values()
        )

    def add_category(self, category: Category) -> None:
        now = datetime.now(UTC)
        category.id = uuid4()
        category.created_at = now
        category.updated_at = now
        self.categories[category.id] = category

    async def get_product(self, product_id: UUID) -> Product | None:
        return self.products.get(product_id)

    async def get_public_product_by_slug(self, slug: str) -> Product | None:
        return next(
            (
                product
                for product in self.products.values()
                if product.slug == slug
                and product.is_active
                and self.categories[product.category_id].is_active
            ),
            None,
        )

    async def list_public_products(
        self,
        filters: ProductFilters,
    ) -> tuple[list[Product], int]:
        products = [
            product
            for product in self.products.values()
            if product.is_active and self.categories[product.category_id].is_active
        ]
        if filters.search:
            search = filters.search.casefold()
            products = [
                product
                for product in products
                if search in product.name.casefold() or search in product.sku.casefold()
            ]
        if filters.category_id is not None:
            products = [
                product for product in products if product.category_id == filters.category_id
            ]
        if filters.min_price_minor is not None:
            products = [
                product for product in products if product.price_minor >= filters.min_price_minor
            ]
        if filters.max_price_minor is not None:
            products = [
                product for product in products if product.price_minor <= filters.max_price_minor
            ]

        sort_key = {
            ProductSortField.CREATED_AT: lambda product: product.created_at,
            ProductSortField.NAME: lambda product: product.name,
            ProductSortField.PRICE: lambda product: product.price_minor,
        }[filters.sort_by]
        products.sort(key=lambda product: product.id)
        products.sort(
            key=sort_key,
            reverse=filters.sort_direction is SortDirection.DESC,
        )
        total = len(products)
        start = (filters.page - 1) * filters.page_size
        return products[start : start + filters.page_size], total

    async def product_slug_exists(
        self,
        slug: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            product.slug == slug and product.id != exclude_id for product in self.products.values()
        )

    async def product_sku_exists(
        self,
        sku: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            product.sku == sku and product.id != exclude_id for product in self.products.values()
        )

    def add_product(self, product: Product) -> None:
        now = datetime.now(UTC)
        product.id = uuid4()
        product.created_at = now
        product.updated_at = now
        self.products[product.id] = product

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_catalog_service() -> tuple[CatalogService, FakeCatalogRepository]:
    repository = FakeCatalogRepository()
    return CatalogService(repository), repository


class FakeProductAvailability:
    def __init__(self) -> None:
        self.product_ids: set[UUID] = set()
        self.active_product_ids: set[UUID] = set()

    async def require_active_product_for_inventory(self, product_id: UUID) -> None:
        if product_id not in self.active_product_ids:
            raise ProductNotFoundError

    async def require_product_for_inventory(self, product_id: UUID) -> None:
        if product_id not in self.product_ids:
            raise ProductNotFoundError


class FakeInventoryRepository:
    def __init__(self) -> None:
        self.warehouses: dict[UUID, Warehouse] = {}
        self.balances: dict[StockKey, StockBalance] = {}
        self.movements: list[InventoryMovement] = []
        self.reservations: dict[UUID, InventoryReservation] = {}
        self.reservations_by_key: dict[str, InventoryReservation] = {}
        self.reservation_key_locks: list[str] = []
        self.commits = 0
        self.rollbacks = 0

    async def list_warehouses(self) -> list[Warehouse]:
        return sorted(
            self.warehouses.values(), key=lambda warehouse: (warehouse.name, warehouse.id)
        )

    async def lock_warehouses(self, warehouse_ids: Iterable[UUID]) -> list[Warehouse]:
        ids = sorted(set(warehouse_ids), key=lambda warehouse_id: warehouse_id.int)
        return [
            self.warehouses[warehouse_id] for warehouse_id in ids if warehouse_id in self.warehouses
        ]

    async def warehouse_code_exists(
        self,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        return any(
            warehouse.code == code and warehouse.id != exclude_id
            for warehouse in self.warehouses.values()
        )

    async def warehouse_has_inventory(self, warehouse_id: UUID) -> bool:
        return any(
            balance.warehouse_id == warehouse_id and (balance.on_hand != 0 or balance.reserved != 0)
            for balance in self.balances.values()
        ) or any(
            reservation.warehouse_id == warehouse_id
            and reservation.status == ReservationStatus.ACTIVE
            for reservation in self.reservations.values()
        )

    def add_warehouse(self, warehouse: Warehouse) -> None:
        now = datetime.now(UTC)
        warehouse.id = uuid4()
        warehouse.created_at = now
        warehouse.updated_at = now
        self.warehouses[warehouse.id] = warehouse

    async def lock_stock_balances(
        self,
        keys: Iterable[StockKey],
    ) -> dict[StockKey, StockBalance]:
        now = datetime.now(UTC)
        ordered_keys = sorted(set(keys), key=lambda key: (key[0].int, key[1].int))
        for key in ordered_keys:
            if key not in self.balances:
                balance = StockBalance(
                    id=uuid4(),
                    warehouse_id=key[0],
                    product_id=key[1],
                    on_hand=0,
                    reserved=0,
                    created_at=now,
                    updated_at=now,
                )
                self.balances[key] = balance
        return {key: self.balances[key] for key in ordered_keys}

    async def list_stock_balances(
        self,
        filters: StockFilters,
    ) -> tuple[list[StockBalance], int]:
        balances = list(self.balances.values())
        if filters.warehouse_id is not None:
            balances = [
                balance for balance in balances if balance.warehouse_id == filters.warehouse_id
            ]
        if filters.product_id is not None:
            balances = [balance for balance in balances if balance.product_id == filters.product_id]
        balances.sort(key=lambda balance: (balance.warehouse_id, balance.product_id))
        total = len(balances)
        start = (filters.page - 1) * filters.page_size
        return balances[start : start + filters.page_size], total

    def add_movement(self, movement: InventoryMovement) -> None:
        movement.created_at = datetime.now(UTC)
        self.movements.append(movement)

    async def list_movements(
        self,
        filters: MovementFilters,
    ) -> tuple[list[InventoryMovement], int]:
        movements = list(self.movements)
        if filters.warehouse_id is not None:
            movements = [
                movement for movement in movements if movement.warehouse_id == filters.warehouse_id
            ]
        if filters.product_id is not None:
            movements = [
                movement for movement in movements if movement.product_id == filters.product_id
            ]
        if filters.movement_type is not None:
            movements = [
                movement
                for movement in movements
                if movement.movement_type == filters.movement_type
            ]
        if filters.operation_id is not None:
            movements = [
                movement for movement in movements if movement.operation_id == filters.operation_id
            ]
        movements.sort(key=lambda movement: (movement.created_at, movement.id), reverse=True)
        total = len(movements)
        start = (filters.page - 1) * filters.page_size
        return movements[start : start + filters.page_size], total

    async def acquire_reservation_key_lock(self, reservation_key: str) -> None:
        self.reservation_key_locks.append(reservation_key)

    async def get_reservation_by_key(
        self,
        reservation_key: str,
    ) -> InventoryReservation | None:
        return self.reservations_by_key.get(reservation_key)

    async def get_reservation(
        self,
        reservation_id: UUID,
        *,
        for_update: bool = False,
    ) -> InventoryReservation | None:
        return self.reservations.get(reservation_id)

    def add_reservation(self, reservation: InventoryReservation) -> None:
        now = datetime.now(UTC)
        reservation.created_at = now
        reservation.updated_at = now
        self.reservations[reservation.id] = reservation
        self.reservations_by_key[reservation.reservation_key] = reservation

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def build_inventory_service(
    *product_ids: UUID,
) -> tuple[InventoryService, FakeInventoryRepository, FakeProductAvailability]:
    repository = FakeInventoryRepository()
    product_availability = FakeProductAvailability()
    product_availability.product_ids.update(product_ids)
    product_availability.active_product_ids.update(product_ids)
    return (
        InventoryService(repository, product_availability),
        repository,
        product_availability,
    )
