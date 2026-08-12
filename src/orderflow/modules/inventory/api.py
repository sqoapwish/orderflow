from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.inventory.dependencies import get_inventory_service
from orderflow.modules.inventory.domain import InventoryMovementType, MovementFilters, StockFilters
from orderflow.modules.inventory.schemas import (
    InventoryMovementResponse,
    MovementPageResponse,
    ReservationCreateRequest,
    ReservationResponse,
    StockAdjustmentRequest,
    StockBalanceResponse,
    StockMutationResponse,
    StockOperationRequest,
    StockPageResponse,
    StockTransferRequest,
    StockTransferResponse,
    WarehouseCreateRequest,
    WarehouseListResponse,
    WarehouseResponse,
    WarehouseUpdateRequest,
)
from orderflow.modules.inventory.service import InventoryService, StockMutationResult

router = APIRouter()

InventoryServiceDependency = Annotated[InventoryService, Depends(get_inventory_service)]
InventoryManagerDependency = Annotated[
    User,
    Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN)),
]


def stock_mutation_response(result: StockMutationResult) -> StockMutationResponse:
    return StockMutationResponse(
        operation_id=result.operation_id,
        balance=StockBalanceResponse.model_validate(result.balance),
    )


@router.get("/warehouses", response_model=WarehouseListResponse, summary="List warehouses")
async def list_warehouses(
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
) -> WarehouseListResponse:
    warehouses = await service.list_warehouses()
    return WarehouseListResponse(
        items=[WarehouseResponse.model_validate(warehouse) for warehouse in warehouses],
        total=len(warehouses),
    )


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a warehouse",
)
async def create_warehouse(
    payload: WarehouseCreateRequest,
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
) -> WarehouseResponse:
    warehouse = await service.create_warehouse(
        name=payload.name,
        code=payload.code,
        location=payload.location,
        is_active=payload.is_active,
    )
    return WarehouseResponse.model_validate(warehouse)


@router.patch(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    summary="Update a warehouse",
)
async def update_warehouse(
    warehouse_id: UUID,
    payload: WarehouseUpdateRequest,
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
) -> WarehouseResponse:
    warehouse = await service.update_warehouse(warehouse_id, payload.to_fields())
    return WarehouseResponse.model_validate(warehouse)


@router.delete(
    "/warehouses/{warehouse_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an empty warehouse",
)
async def archive_warehouse(
    warehouse_id: UUID,
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
) -> Response:
    await service.archive_warehouse(warehouse_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stock", response_model=StockPageResponse, summary="List stock balances")
async def list_stock(
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
) -> StockPageResponse:
    result = await service.list_stock(
        StockFilters(
            page=page,
            page_size=page_size,
            warehouse_id=warehouse_id,
            product_id=product_id,
        )
    )
    return StockPageResponse(
        items=[StockBalanceResponse.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.post(
    "/stock/receipts",
    response_model=StockMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Receive physical stock",
)
async def receive_stock(
    payload: StockOperationRequest,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> StockMutationResponse:
    return stock_mutation_response(
        await service.receive_stock(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            reason=payload.reason,
            actor_id=actor.id,
        )
    )


@router.post(
    "/stock/write-offs",
    response_model=StockMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Write off available physical stock",
)
async def write_off_stock(
    payload: StockOperationRequest,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> StockMutationResponse:
    return stock_mutation_response(
        await service.write_off_stock(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            quantity=payload.quantity,
            reason=payload.reason,
            actor_id=actor.id,
        )
    )


@router.post(
    "/stock/adjustments",
    response_model=StockMutationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Set counted physical stock",
)
async def adjust_stock(
    payload: StockAdjustmentRequest,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> StockMutationResponse:
    return stock_mutation_response(
        await service.adjust_stock(
            warehouse_id=payload.warehouse_id,
            product_id=payload.product_id,
            on_hand=payload.on_hand,
            reason=payload.reason,
            actor_id=actor.id,
        )
    )


@router.post(
    "/stock/transfers",
    response_model=StockTransferResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Transfer available stock between warehouses",
)
async def transfer_stock(
    payload: StockTransferRequest,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> StockTransferResponse:
    result = await service.transfer_stock(
        source_warehouse_id=payload.source_warehouse_id,
        target_warehouse_id=payload.target_warehouse_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        reason=payload.reason,
        actor_id=actor.id,
    )
    return StockTransferResponse(
        operation_id=result.operation_id,
        source=StockBalanceResponse.model_validate(result.source),
        target=StockBalanceResponse.model_validate(result.target),
    )


@router.get(
    "/movements",
    response_model=MovementPageResponse,
    summary="List immutable inventory movements",
)
async def list_movements(
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    warehouse_id: UUID | None = None,
    product_id: UUID | None = None,
    movement_type: InventoryMovementType | None = None,
    operation_id: UUID | None = None,
) -> MovementPageResponse:
    result = await service.list_movements(
        MovementFilters(
            page=page,
            page_size=page_size,
            warehouse_id=warehouse_id,
            product_id=product_id,
            movement_type=movement_type,
            operation_id=operation_id,
        )
    )
    return MovementPageResponse(
        items=[InventoryMovementResponse.model_validate(item) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.post(
    "/reservations",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an idempotent stock reservation",
)
async def reserve_stock(
    payload: ReservationCreateRequest,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> ReservationResponse:
    reservation = await service.reserve_stock(
        reservation_key=payload.reservation_key,
        warehouse_id=payload.warehouse_id,
        product_id=payload.product_id,
        quantity=payload.quantity,
        actor_id=actor.id,
    )
    return ReservationResponse.model_validate(reservation)


@router.get(
    "/reservations/{reservation_id}",
    response_model=ReservationResponse,
    summary="Get a stock reservation",
)
async def get_reservation(
    reservation_id: UUID,
    service: InventoryServiceDependency,
    _: InventoryManagerDependency,
) -> ReservationResponse:
    return ReservationResponse.model_validate(await service.get_reservation(reservation_id))


@router.post(
    "/reservations/{reservation_id}/release",
    response_model=ReservationResponse,
    summary="Release a stock reservation",
)
async def release_reservation(
    reservation_id: UUID,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> ReservationResponse:
    reservation = await service.release_reservation(reservation_id, actor_id=actor.id)
    return ReservationResponse.model_validate(reservation)


@router.post(
    "/reservations/{reservation_id}/consume",
    response_model=ReservationResponse,
    summary="Consume a stock reservation",
)
async def consume_reservation(
    reservation_id: UUID,
    service: InventoryServiceDependency,
    actor: InventoryManagerDependency,
) -> ReservationResponse:
    reservation = await service.consume_reservation(reservation_id, actor_id=actor.id)
    return ReservationResponse.model_validate(reservation)
