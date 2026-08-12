from dataclasses import dataclass
from math import ceil
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from orderflow.modules.inventory.domain import (
    InventoryMovementType,
    MovementFilters,
    ReservationStatus,
    StockFilters,
    WarehouseUpdateFields,
)
from orderflow.modules.inventory.errors import (
    AdjustmentBelowReservedError,
    InactiveWarehouseError,
    InsufficientAvailableStockError,
    InventoryWriteConflictError,
    NoStockChangeError,
    ReservationKeyConflictError,
    ReservationNotFoundError,
    ReservationStateConflictError,
    WarehouseCodeConflictError,
    WarehouseNotEmptyError,
    WarehouseNotFoundError,
)
from orderflow.modules.inventory.models import (
    InventoryMovement,
    InventoryReservation,
    StockBalance,
    Warehouse,
)
from orderflow.modules.inventory.repository import InventoryRepositoryProtocol, StockKey


class ProductAvailabilityProtocol(Protocol):
    async def require_active_product_for_inventory(self, product_id: UUID) -> None: ...

    async def require_product_for_inventory(self, product_id: UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class StockPage:
    items: list[StockBalance]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class MovementPage:
    items: list[InventoryMovement]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class StockMutationResult:
    operation_id: UUID
    balance: StockBalance


@dataclass(frozen=True, slots=True)
class StockTransferResult:
    operation_id: UUID
    source: StockBalance
    target: StockBalance


class InventoryService:
    def __init__(
        self,
        repository: InventoryRepositoryProtocol,
        product_availability: ProductAvailabilityProtocol,
    ) -> None:
        self._repository = repository
        self._product_availability = product_availability

    async def list_warehouses(self) -> list[Warehouse]:
        return await self._repository.list_warehouses()

    async def create_warehouse(
        self,
        *,
        name: str,
        code: str,
        location: str | None,
        is_active: bool,
    ) -> Warehouse:
        if await self._repository.warehouse_code_exists(code):
            raise WarehouseCodeConflictError
        warehouse = Warehouse(
            name=name,
            code=code,
            location=location,
            is_active=is_active,
        )
        self._repository.add_warehouse(warehouse)
        await self._save()
        return warehouse

    async def update_warehouse(
        self,
        warehouse_id: UUID,
        fields: WarehouseUpdateFields,
    ) -> Warehouse:
        warehouse = (await self._lock_warehouses([warehouse_id], require_active=False))[
            warehouse_id
        ]
        if (
            "code" in fields
            and fields["code"] != warehouse.code
            and await self._repository.warehouse_code_exists(fields["code"], warehouse.id)
        ):
            raise WarehouseCodeConflictError
        target_is_active = fields.get("is_active", warehouse.is_active)
        if warehouse.is_active and not target_is_active:
            await self._ensure_warehouse_empty(warehouse.id)
        for field_name, value in fields.items():
            setattr(warehouse, field_name, value)
        await self._save()
        return warehouse

    async def archive_warehouse(self, warehouse_id: UUID) -> None:
        warehouse = (await self._lock_warehouses([warehouse_id], require_active=False))[
            warehouse_id
        ]
        if not warehouse.is_active:
            return
        await self._ensure_warehouse_empty(warehouse.id)
        warehouse.is_active = False
        await self._save()

    async def list_stock(self, filters: StockFilters) -> StockPage:
        items, total = await self._repository.list_stock_balances(filters)
        return StockPage(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def receive_stock(
        self,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        quantity: int,
        reason: str | None,
        actor_id: UUID,
    ) -> StockMutationResult:
        await self._prepare_stock_operation(
            [warehouse_id],
            product_id,
            require_active_product=True,
        )
        balance = await self._lock_balance(warehouse_id, product_id)
        balance.on_hand += quantity
        operation_id = uuid4()
        self._record_movement(
            operation_id=operation_id,
            balance=balance,
            movement_type=InventoryMovementType.RECEIPT,
            delta_on_hand=quantity,
            delta_reserved=0,
            actor_id=actor_id,
            reason=reason,
        )
        await self._save()
        return StockMutationResult(operation_id=operation_id, balance=balance)

    async def write_off_stock(
        self,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        quantity: int,
        reason: str | None,
        actor_id: UUID,
    ) -> StockMutationResult:
        await self._prepare_stock_operation(
            [warehouse_id],
            product_id,
            require_active_product=False,
        )
        balance = await self._lock_balance(warehouse_id, product_id)
        if balance.available < quantity:
            raise InsufficientAvailableStockError
        balance.on_hand -= quantity
        operation_id = uuid4()
        self._record_movement(
            operation_id=operation_id,
            balance=balance,
            movement_type=InventoryMovementType.WRITE_OFF,
            delta_on_hand=-quantity,
            delta_reserved=0,
            actor_id=actor_id,
            reason=reason,
        )
        await self._save()
        return StockMutationResult(operation_id=operation_id, balance=balance)

    async def adjust_stock(
        self,
        *,
        warehouse_id: UUID,
        product_id: UUID,
        on_hand: int,
        reason: str,
        actor_id: UUID,
    ) -> StockMutationResult:
        await self._prepare_stock_operation(
            [warehouse_id],
            product_id,
            require_active_product=False,
        )
        balance = await self._lock_balance(warehouse_id, product_id)
        if on_hand < balance.reserved:
            raise AdjustmentBelowReservedError
        delta = on_hand - balance.on_hand
        if delta == 0:
            raise NoStockChangeError
        balance.on_hand = on_hand
        operation_id = uuid4()
        self._record_movement(
            operation_id=operation_id,
            balance=balance,
            movement_type=InventoryMovementType.ADJUSTMENT,
            delta_on_hand=delta,
            delta_reserved=0,
            actor_id=actor_id,
            reason=reason,
        )
        await self._save()
        return StockMutationResult(operation_id=operation_id, balance=balance)

    async def transfer_stock(
        self,
        *,
        source_warehouse_id: UUID,
        target_warehouse_id: UUID,
        product_id: UUID,
        quantity: int,
        reason: str | None,
        actor_id: UUID,
    ) -> StockTransferResult:
        if source_warehouse_id == target_warehouse_id:
            raise NoStockChangeError
        await self._prepare_stock_operation(
            [source_warehouse_id, target_warehouse_id],
            product_id,
            require_active_product=False,
        )
        balances = await self._repository.lock_stock_balances(
            [
                (source_warehouse_id, product_id),
                (target_warehouse_id, product_id),
            ]
        )
        source = balances[(source_warehouse_id, product_id)]
        target = balances[(target_warehouse_id, product_id)]
        if source.available < quantity:
            raise InsufficientAvailableStockError
        source.on_hand -= quantity
        target.on_hand += quantity
        operation_id = uuid4()
        self._record_movement(
            operation_id=operation_id,
            balance=source,
            movement_type=InventoryMovementType.TRANSFER_OUT,
            delta_on_hand=-quantity,
            delta_reserved=0,
            actor_id=actor_id,
            reason=reason,
        )
        self._record_movement(
            operation_id=operation_id,
            balance=target,
            movement_type=InventoryMovementType.TRANSFER_IN,
            delta_on_hand=quantity,
            delta_reserved=0,
            actor_id=actor_id,
            reason=reason,
        )
        await self._save()
        return StockTransferResult(operation_id=operation_id, source=source, target=target)

    async def list_movements(self, filters: MovementFilters) -> MovementPage:
        items, total = await self._repository.list_movements(filters)
        return MovementPage(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def get_reservation(self, reservation_id: UUID) -> InventoryReservation:
        reservation = await self._repository.get_reservation(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError
        return reservation

    async def reserve_stock(
        self,
        *,
        reservation_key: str,
        warehouse_id: UUID,
        product_id: UUID,
        quantity: int,
        actor_id: UUID,
    ) -> InventoryReservation:
        await self._repository.acquire_reservation_key_lock(reservation_key)
        existing = await self._repository.get_reservation_by_key(reservation_key)
        if existing is not None:
            if (
                existing.warehouse_id != warehouse_id
                or existing.product_id != product_id
                or existing.quantity != quantity
            ):
                raise ReservationKeyConflictError
            return existing

        await self._prepare_stock_operation(
            [warehouse_id],
            product_id,
            require_active_product=True,
        )
        balance = await self._lock_balance(warehouse_id, product_id)
        if balance.available < quantity:
            raise InsufficientAvailableStockError
        reservation = InventoryReservation(
            id=uuid4(),
            reservation_key=reservation_key,
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=quantity,
            status=ReservationStatus.ACTIVE,
            created_by_user_id=actor_id,
        )
        self._repository.add_reservation(reservation)
        # The movement references this reservation by foreign key. Flush the parent row
        # first while keeping both records in the same transaction.
        await self._flush()
        balance.reserved += quantity
        self._record_movement(
            operation_id=uuid4(),
            balance=balance,
            movement_type=InventoryMovementType.RESERVATION_CREATED,
            delta_on_hand=0,
            delta_reserved=quantity,
            actor_id=actor_id,
            reservation_id=reservation.id,
        )
        await self._save()
        return reservation

    async def release_reservation(
        self,
        reservation_id: UUID,
        *,
        actor_id: UUID,
    ) -> InventoryReservation:
        reservation = await self._require_locked_reservation(reservation_id)
        if reservation.status == ReservationStatus.RELEASED:
            return reservation
        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationStateConflictError(target="released")
        balance = await self._lock_balance(reservation.warehouse_id, reservation.product_id)
        if balance.reserved < reservation.quantity:
            raise InventoryWriteConflictError
        balance.reserved -= reservation.quantity
        reservation.status = ReservationStatus.RELEASED
        self._record_movement(
            operation_id=uuid4(),
            balance=balance,
            movement_type=InventoryMovementType.RESERVATION_RELEASED,
            delta_on_hand=0,
            delta_reserved=-reservation.quantity,
            actor_id=actor_id,
            reservation_id=reservation.id,
        )
        await self._save()
        return reservation

    async def consume_reservation(
        self,
        reservation_id: UUID,
        *,
        actor_id: UUID,
    ) -> InventoryReservation:
        reservation = await self._require_locked_reservation(reservation_id)
        if reservation.status == ReservationStatus.CONSUMED:
            return reservation
        if reservation.status != ReservationStatus.ACTIVE:
            raise ReservationStateConflictError(target="consumed")
        balance = await self._lock_balance(reservation.warehouse_id, reservation.product_id)
        if balance.reserved < reservation.quantity or balance.on_hand < reservation.quantity:
            raise InventoryWriteConflictError
        balance.reserved -= reservation.quantity
        balance.on_hand -= reservation.quantity
        reservation.status = ReservationStatus.CONSUMED
        self._record_movement(
            operation_id=uuid4(),
            balance=balance,
            movement_type=InventoryMovementType.RESERVATION_CONSUMED,
            delta_on_hand=-reservation.quantity,
            delta_reserved=-reservation.quantity,
            actor_id=actor_id,
            reservation_id=reservation.id,
        )
        await self._save()
        return reservation

    async def _prepare_stock_operation(
        self,
        warehouse_ids: list[UUID],
        product_id: UUID,
        *,
        require_active_product: bool,
    ) -> None:
        if require_active_product:
            await self._product_availability.require_active_product_for_inventory(product_id)
        else:
            await self._product_availability.require_product_for_inventory(product_id)
        await self._lock_warehouses(warehouse_ids, require_active=True)

    async def _lock_warehouses(
        self,
        warehouse_ids: list[UUID],
        *,
        require_active: bool,
    ) -> dict[UUID, Warehouse]:
        expected = set(warehouse_ids)
        warehouses = await self._repository.lock_warehouses(expected)
        by_id = {warehouse.id: warehouse for warehouse in warehouses}
        if set(by_id) != expected:
            raise WarehouseNotFoundError
        if require_active and any(not warehouse.is_active for warehouse in warehouses):
            raise InactiveWarehouseError
        return by_id

    async def _lock_balance(self, warehouse_id: UUID, product_id: UUID) -> StockBalance:
        key: StockKey = (warehouse_id, product_id)
        balances = await self._repository.lock_stock_balances([key])
        try:
            return balances[key]
        except KeyError:
            raise InventoryWriteConflictError from None

    async def _require_locked_reservation(
        self,
        reservation_id: UUID,
    ) -> InventoryReservation:
        reservation = await self._repository.get_reservation(reservation_id, for_update=True)
        if reservation is None:
            raise ReservationNotFoundError
        await self._lock_warehouses([reservation.warehouse_id], require_active=False)
        return reservation

    async def _ensure_warehouse_empty(self, warehouse_id: UUID) -> None:
        if await self._repository.warehouse_has_inventory(warehouse_id):
            raise WarehouseNotEmptyError

    def _record_movement(
        self,
        *,
        operation_id: UUID,
        balance: StockBalance,
        movement_type: InventoryMovementType,
        delta_on_hand: int,
        delta_reserved: int,
        actor_id: UUID,
        reason: str | None = None,
        reservation_id: UUID | None = None,
    ) -> None:
        self._repository.add_movement(
            InventoryMovement(
                id=uuid4(),
                operation_id=operation_id,
                warehouse_id=balance.warehouse_id,
                product_id=balance.product_id,
                reservation_id=reservation_id,
                movement_type=movement_type,
                delta_on_hand=delta_on_hand,
                delta_reserved=delta_reserved,
                balance_on_hand=balance.on_hand,
                balance_reserved=balance.reserved,
                reason=reason,
                created_by_user_id=actor_id,
            )
        )

    async def _flush(self) -> None:
        try:
            await self._repository.flush()
        except IntegrityError:
            await self._repository.rollback()
            raise InventoryWriteConflictError from None

    async def _save(self) -> None:
        await self._flush()
        try:
            await self._repository.commit()
        except IntegrityError:
            await self._repository.rollback()
            raise InventoryWriteConflictError from None
