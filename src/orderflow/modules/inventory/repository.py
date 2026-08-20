from collections.abc import Iterable
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import exists, func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from orderflow.modules.catalog.models import Product
from orderflow.modules.inventory.domain import (
    MovementFilters,
    ProductAvailability,
    ReservationStatus,
    StockFilters,
)
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)

StockKey = tuple[UUID, UUID]


class InventoryRepositoryProtocol(Protocol):
    async def list_warehouses(self) -> list[Warehouse]: ...

    async def list_product_availability(
        self,
        product_id: UUID,
    ) -> list[ProductAvailability]: ...

    async def lock_warehouses(self, warehouse_ids: Iterable[UUID]) -> list[Warehouse]: ...

    async def warehouse_code_exists(
        self,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool: ...

    async def warehouse_has_inventory(self, warehouse_id: UUID) -> bool: ...

    def add_warehouse(self, warehouse: Warehouse) -> None: ...

    async def lock_stock_balances(
        self,
        keys: Iterable[StockKey],
    ) -> dict[StockKey, StockBalance]: ...

    async def list_stock_balances(
        self,
        filters: StockFilters,
    ) -> tuple[list[StockBalance], int]: ...

    def add_movement(self, movement: InventoryMovement) -> None: ...

    async def list_movements(
        self,
        filters: MovementFilters,
    ) -> tuple[list[InventoryMovement], int]: ...

    async def acquire_reservation_key_lock(self, reservation_key: str) -> None: ...

    async def get_reservation_by_key(
        self,
        reservation_key: str,
    ) -> InventoryReservation | None: ...

    async def get_reservation(
        self,
        reservation_id: UUID,
        *,
        for_update: bool = False,
    ) -> InventoryReservation | None: ...

    def add_reservation(self, reservation: InventoryReservation) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_warehouses(self) -> list[Warehouse]:
        result = await self._session.execute(
            select(Warehouse).order_by(Warehouse.name, Warehouse.id)
        )
        return list(result.scalars().all())

    async def list_product_availability(
        self,
        product_id: UUID,
    ) -> list[ProductAvailability]:
        available = StockBalance.on_hand - StockBalance.reserved
        rows = (
            await self._session.execute(
                select(
                    Warehouse.id,
                    Warehouse.name,
                    Warehouse.code,
                    available.label("available"),
                )
                .select_from(StockBalance)
                .join(Warehouse, Warehouse.id == StockBalance.warehouse_id)
                .join(Product, Product.id == StockBalance.product_id)
                .where(
                    StockBalance.product_id == product_id,
                    Product.is_active.is_(True),
                    Warehouse.is_active.is_(True),
                    available > 0,
                )
                .order_by(available.desc(), Warehouse.name, Warehouse.id)
            )
        ).all()
        return [
            ProductAvailability(
                warehouse_id=row.id,
                warehouse_name=row.name,
                warehouse_code=row.code,
                available=row.available,
            )
            for row in rows
        ]

    async def lock_warehouses(self, warehouse_ids: Iterable[UUID]) -> list[Warehouse]:
        ordered_ids = sorted(set(warehouse_ids), key=lambda warehouse_id: warehouse_id.int)
        if not ordered_ids:
            return []
        statement = (
            select(Warehouse)
            .where(Warehouse.id.in_(ordered_ids))
            .order_by(Warehouse.id)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def warehouse_code_exists(
        self,
        code: str,
        exclude_id: UUID | None = None,
    ) -> bool:
        conditions: list[ColumnElement[bool]] = [Warehouse.code == code]
        if exclude_id is not None:
            conditions.append(Warehouse.id != exclude_id)
        return bool(await self._session.scalar(select(exists().where(*conditions))))

    async def warehouse_has_inventory(self, warehouse_id: UUID) -> bool:
        stock_exists = await self._session.scalar(
            select(
                exists().where(
                    StockBalance.warehouse_id == warehouse_id,
                    or_(StockBalance.on_hand != 0, StockBalance.reserved != 0),
                )
            )
        )
        if stock_exists:
            return True
        return bool(
            await self._session.scalar(
                select(
                    exists().where(
                        InventoryReservation.warehouse_id == warehouse_id,
                        InventoryReservation.status == ReservationStatus.ACTIVE,
                    )
                )
            )
        )

    def add_warehouse(self, warehouse: Warehouse) -> None:
        self._session.add(warehouse)

    async def lock_stock_balances(
        self,
        keys: Iterable[StockKey],
    ) -> dict[StockKey, StockBalance]:
        ordered_keys = sorted(set(keys), key=lambda key: (key[0].int, key[1].int))
        if not ordered_keys:
            return {}
        values = [
            {
                "id": uuid4(),
                "warehouse_id": warehouse_id,
                "product_id": product_id,
                "on_hand": 0,
                "reserved": 0,
            }
            for warehouse_id, product_id in ordered_keys
        ]
        insert_statement = postgresql_insert(StockBalance).values(values)
        await self._session.execute(
            insert_statement.on_conflict_do_nothing(
                index_elements=[StockBalance.warehouse_id, StockBalance.product_id]
            )
        )
        statement = (
            select(StockBalance)
            .where(tuple_(StockBalance.warehouse_id, StockBalance.product_id).in_(ordered_keys))
            .order_by(StockBalance.warehouse_id, StockBalance.product_id)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        balances = list(result.scalars().all())
        return {(balance.warehouse_id, balance.product_id): balance for balance in balances}

    async def list_stock_balances(
        self,
        filters: StockFilters,
    ) -> tuple[list[StockBalance], int]:
        conditions: list[ColumnElement[bool]] = []
        if filters.warehouse_id is not None:
            conditions.append(StockBalance.warehouse_id == filters.warehouse_id)
        if filters.product_id is not None:
            conditions.append(StockBalance.product_id == filters.product_id)
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(StockBalance).where(*conditions)
                )
            )
            or 0
        )
        statement = (
            select(StockBalance)
            .where(*conditions)
            .order_by(StockBalance.warehouse_id, StockBalance.product_id)
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    def add_movement(self, movement: InventoryMovement) -> None:
        self._session.add(movement)

    async def list_movements(
        self,
        filters: MovementFilters,
    ) -> tuple[list[InventoryMovement], int]:
        conditions: list[ColumnElement[bool]] = []
        if filters.warehouse_id is not None:
            conditions.append(InventoryMovement.warehouse_id == filters.warehouse_id)
        if filters.product_id is not None:
            conditions.append(InventoryMovement.product_id == filters.product_id)
        if filters.movement_type is not None:
            conditions.append(InventoryMovement.movement_type == filters.movement_type)
        if filters.operation_id is not None:
            conditions.append(InventoryMovement.operation_id == filters.operation_id)
        total = int(
            (
                await self._session.scalar(
                    select(func.count()).select_from(InventoryMovement).where(*conditions)
                )
            )
            or 0
        )
        statement = (
            select(InventoryMovement)
            .where(*conditions)
            .order_by(InventoryMovement.created_at.desc(), InventoryMovement.id.desc())
            .offset((filters.page - 1) * filters.page_size)
            .limit(filters.page_size)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all()), total

    async def acquire_reservation_key_lock(self, reservation_key: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:reservation_key, 20260812))"),
            {"reservation_key": reservation_key},
        )

    async def get_reservation_by_key(
        self,
        reservation_key: str,
    ) -> InventoryReservation | None:
        result = await self._session.execute(
            select(InventoryReservation).where(
                InventoryReservation.reservation_key == reservation_key
            )
        )
        return result.scalar_one_or_none()

    async def get_reservation(
        self,
        reservation_id: UUID,
        *,
        for_update: bool = False,
    ) -> InventoryReservation | None:
        statement = select(InventoryReservation).where(InventoryReservation.id == reservation_id)
        if for_update:
            statement = statement.with_for_update()
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def add_reservation(self, reservation: InventoryReservation) -> None:
        self._session.add(reservation)

    async def flush(self) -> None:
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
