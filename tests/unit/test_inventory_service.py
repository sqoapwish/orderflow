from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from orderflow.modules.catalog.errors import ProductNotFoundError
from orderflow.modules.inventory.domain import (
    InventoryMovementType,
    MovementFilters,
    ReservationStatus,
    StockFilters,
)
from orderflow.modules.inventory.errors import (
    AdjustmentBelowReservedError,
    InactiveWarehouseError,
    InsufficientAvailableStockError,
    InventoryWriteConflictError,
    NoStockChangeError,
    ReservationKeyConflictError,
    ReservationStateConflictError,
    WarehouseCodeConflictError,
    WarehouseNotEmptyError,
    WarehouseNotFoundError,
)
from orderflow.modules.inventory.models import InventoryMovement, InventoryReservation, Warehouse
from orderflow.modules.inventory.service import InventoryService
from tests.fakes import FakeInventoryRepository, FakeProductAvailability, build_inventory_service


async def create_warehouse(
    service: InventoryService,
    *,
    name: str = "Main warehouse",
    code: str = "MAIN",
    location: str | None = "Moscow",
    is_active: bool = True,
) -> Warehouse:
    return await service.create_warehouse(
        name=name,
        code=code,
        location=location,
        is_active=is_active,
    )


async def receive(
    service: InventoryService,
    warehouse_id: UUID,
    product_id: UUID,
    quantity: int,
    actor_id: UUID,
) -> None:
    await service.receive_stock(
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=quantity,
        reason="Supplier delivery",
        actor_id=actor_id,
    )


async def test_warehouse_identity_update_and_safe_archiving() -> None:
    service, _, _ = build_inventory_service()
    warehouse = await create_warehouse(service)

    with pytest.raises(WarehouseCodeConflictError):
        await create_warehouse(service, name="Duplicate", code="MAIN")
    with pytest.raises(WarehouseNotFoundError):
        await service.update_warehouse(uuid4(), {"name": "Missing"})

    updated = await service.update_warehouse(
        warehouse.id,
        {"name": "Central warehouse", "code": "CENTRAL", "location": None},
    )
    assert updated.name == "Central warehouse"
    assert updated.code == "CENTRAL"
    assert updated.location is None

    await service.archive_warehouse(warehouse.id)
    await service.archive_warehouse(warehouse.id)
    assert warehouse.is_active is False


async def test_receipt_write_off_adjustment_transfer_and_history() -> None:
    product_id = uuid4()
    actor_id = uuid4()
    service, repository, _ = build_inventory_service(product_id)
    source = await create_warehouse(service)
    target = await create_warehouse(
        service,
        name="North warehouse",
        code="NORTH",
        location="Saint Petersburg",
    )

    received = await service.receive_stock(
        warehouse_id=source.id,
        product_id=product_id,
        quantity=10,
        reason="Supplier delivery",
        actor_id=actor_id,
    )
    assert received.balance.on_hand == 10
    assert received.balance.available == 10

    transferred = await service.transfer_stock(
        source_warehouse_id=source.id,
        target_warehouse_id=target.id,
        product_id=product_id,
        quantity=4,
        reason="Rebalance",
        actor_id=actor_id,
    )
    assert transferred.source.on_hand == 6
    assert transferred.target.on_hand == 4
    transfer_movements = [
        movement
        for movement in repository.movements
        if movement.operation_id == transferred.operation_id
    ]
    assert {movement.movement_type for movement in transfer_movements} == {
        InventoryMovementType.TRANSFER_IN,
        InventoryMovementType.TRANSFER_OUT,
    }

    written_off = await service.write_off_stock(
        warehouse_id=target.id,
        product_id=product_id,
        quantity=1,
        reason="Damaged package",
        actor_id=actor_id,
    )
    assert written_off.balance.on_hand == 3

    adjusted = await service.adjust_stock(
        warehouse_id=source.id,
        product_id=product_id,
        on_hand=8,
        reason="Cycle count correction",
        actor_id=actor_id,
    )
    assert adjusted.balance.on_hand == 8

    page = await service.list_movements(
        MovementFilters(warehouse_id=source.id, product_id=product_id, page_size=2)
    )
    assert page.total == 3
    assert page.total_pages == 2
    assert len(page.items) == 2

    stock_page = await service.list_stock(StockFilters(product_id=product_id, page_size=1))
    assert stock_page.total == 2
    assert stock_page.total_pages == 2


async def test_reservation_is_idempotent_and_prevents_overselling() -> None:
    product_id = uuid4()
    actor_id = uuid4()
    service, repository, _ = build_inventory_service(product_id)
    warehouse = await create_warehouse(service)
    await receive(service, warehouse.id, product_id, 10, actor_id)

    reservation = await service.reserve_stock(
        reservation_key="order-42-item-1",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=7,
        actor_id=actor_id,
    )
    replay = await service.reserve_stock(
        reservation_key="order-42-item-1",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=7,
        actor_id=actor_id,
    )
    balance = repository.balances[(warehouse.id, product_id)]

    assert replay.id == reservation.id
    assert balance.on_hand == 10
    assert balance.reserved == 7
    assert balance.available == 3
    assert repository.reservation_key_locks == ["order-42-item-1", "order-42-item-1"]
    assert (
        sum(
            movement.movement_type == InventoryMovementType.RESERVATION_CREATED
            for movement in repository.movements
        )
        == 1
    )

    with pytest.raises(ReservationKeyConflictError):
        await service.reserve_stock(
            reservation_key="order-42-item-1",
            warehouse_id=warehouse.id,
            product_id=product_id,
            quantity=6,
            actor_id=actor_id,
        )
    with pytest.raises(InsufficientAvailableStockError):
        await service.reserve_stock(
            reservation_key="order-43-item-1",
            warehouse_id=warehouse.id,
            product_id=product_id,
            quantity=4,
            actor_id=actor_id,
        )
    with pytest.raises(InsufficientAvailableStockError):
        await service.write_off_stock(
            warehouse_id=warehouse.id,
            product_id=product_id,
            quantity=4,
            reason="Would consume reserved stock",
            actor_id=actor_id,
        )


async def test_new_reservation_is_flushed_before_referencing_movement() -> None:
    class FlushOrderRepository(FakeInventoryRepository):
        def __init__(self) -> None:
            super().__init__()
            self.events: list[str] = []

        def add_reservation(self, reservation: InventoryReservation) -> None:
            super().add_reservation(reservation)
            self.events.append("reservation")

        def add_movement(self, movement: InventoryMovement) -> None:
            super().add_movement(movement)
            self.events.append("movement")

        async def flush(self) -> None:
            self.events.append("flush")
            await super().flush()

        async def commit(self) -> None:
            self.events.append("commit")
            await super().commit()

    product_id = uuid4()
    actor_id = uuid4()
    repository = FlushOrderRepository()
    availability = FakeProductAvailability()
    availability.product_ids.add(product_id)
    availability.active_product_ids.add(product_id)
    service = InventoryService(repository, availability)
    warehouse = await create_warehouse(service)
    await receive(service, warehouse.id, product_id, 1, actor_id)
    repository.events.clear()

    await service.reserve_stock(
        reservation_key="flush-before-movement",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=1,
        actor_id=actor_id,
    )

    assert repository.events == ["reservation", "flush", "movement", "flush", "commit"]


async def test_reservation_release_and_consume_are_terminal_and_idempotent() -> None:
    product_id = uuid4()
    actor_id = uuid4()
    service, repository, _ = build_inventory_service(product_id)
    warehouse = await create_warehouse(service)
    await receive(service, warehouse.id, product_id, 10, actor_id)

    released = await service.reserve_stock(
        reservation_key="release-me",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=3,
        actor_id=actor_id,
    )
    await service.release_reservation(released.id, actor_id=actor_id)
    await service.release_reservation(released.id, actor_id=actor_id)
    assert released.status == ReservationStatus.RELEASED
    assert repository.balances[(warehouse.id, product_id)].reserved == 0
    with pytest.raises(ReservationStateConflictError):
        await service.consume_reservation(released.id, actor_id=actor_id)

    consumed = await service.reserve_stock(
        reservation_key="consume-me",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=4,
        actor_id=actor_id,
    )
    await service.consume_reservation(consumed.id, actor_id=actor_id)
    await service.consume_reservation(consumed.id, actor_id=actor_id)
    balance = repository.balances[(warehouse.id, product_id)]
    assert consumed.status == ReservationStatus.CONSUMED
    assert balance.on_hand == 6
    assert balance.reserved == 0
    with pytest.raises(ReservationStateConflictError):
        await service.release_reservation(consumed.id, actor_id=actor_id)


async def test_stock_invariants_block_invalid_operations_and_warehouse_archive() -> None:
    product_id = uuid4()
    actor_id = uuid4()
    service, _, availability = build_inventory_service(product_id)
    warehouse = await create_warehouse(service)
    inactive = await create_warehouse(
        service,
        name="Inactive warehouse",
        code="INACTIVE",
        is_active=False,
    )
    await receive(service, warehouse.id, product_id, 5, actor_id)
    reservation = await service.reserve_stock(
        reservation_key="protected-stock",
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=3,
        actor_id=actor_id,
    )

    with pytest.raises(AdjustmentBelowReservedError):
        await service.adjust_stock(
            warehouse_id=warehouse.id,
            product_id=product_id,
            on_hand=2,
            reason="Invalid count",
            actor_id=actor_id,
        )
    with pytest.raises(NoStockChangeError):
        await service.adjust_stock(
            warehouse_id=warehouse.id,
            product_id=product_id,
            on_hand=5,
            reason="No difference",
            actor_id=actor_id,
        )
    with pytest.raises(WarehouseNotEmptyError):
        await service.archive_warehouse(warehouse.id)
    with pytest.raises(InactiveWarehouseError):
        await receive(service, inactive.id, product_id, 1, actor_id)

    availability.active_product_ids.clear()
    with pytest.raises(ProductNotFoundError):
        await receive(service, warehouse.id, product_id, 1, actor_id)

    await service.release_reservation(reservation.id, actor_id=actor_id)
    await service.write_off_stock(
        warehouse_id=warehouse.id,
        product_id=product_id,
        quantity=5,
        reason="Clear warehouse",
        actor_id=actor_id,
    )
    await service.archive_warehouse(warehouse.id)


async def test_integrity_error_rolls_back_as_stable_inventory_conflict() -> None:
    class FailingRepository(FakeInventoryRepository):
        async def flush(self) -> None:
            raise IntegrityError("insert", {}, Exception("unique race"))

    repository = FailingRepository()
    service = InventoryService(repository, FakeProductAvailability())

    with pytest.raises(InventoryWriteConflictError):
        await create_warehouse(service)

    assert repository.rollbacks == 1
