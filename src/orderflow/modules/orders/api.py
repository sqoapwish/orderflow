from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.orders.dependencies import get_order_service
from orderflow.modules.orders.domain import OrderFilters, OrderStatus
from orderflow.modules.orders.schemas import OrderPageResponse, OrderResponse
from orderflow.modules.orders.service import OrderService
from orderflow.modules.payments.dependencies import get_payment_service
from orderflow.modules.payments.service import PaymentService

router = APIRouter()

OrderServiceDependency = Annotated[OrderService, Depends(get_order_service)]
OrderActorDependency = Annotated[
    User,
    Depends(require_roles(UserRole.CUSTOMER, UserRole.MANAGER, UserRole.ADMIN)),
]
OrderCustomerDependency = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
OrderPaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]


@router.post(
    "/checkout",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Atomically create an order and reserve its stock",
)
async def checkout(
    response: Response,
    service: OrderServiceDependency,
    customer: OrderCustomerDependency,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> OrderResponse:
    result = await service.checkout(
        customer_id=customer.id,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return OrderResponse.from_bundle(result.bundle)


@router.get("", response_model=OrderPageResponse, summary="List visible orders")
async def list_orders(
    service: OrderServiceDependency,
    actor: OrderActorDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    customer_id: UUID | None = None,
    order_status: Annotated[OrderStatus | None, Query(alias="status")] = None,
) -> OrderPageResponse:
    result = await service.list_orders(
        OrderFilters(
            page=page,
            page_size=page_size,
            customer_id=customer_id,
            status=order_status,
        ),
        requester_id=actor.id,
        requester_role=actor.role,
    )
    return OrderPageResponse(
        items=[OrderResponse.from_bundle(bundle) for bundle in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get("/{order_id}", response_model=OrderResponse, summary="Get a visible order")
async def get_order(
    order_id: UUID,
    service: OrderServiceDependency,
    actor: OrderActorDependency,
) -> OrderResponse:
    bundle = await service.get_order(
        order_id,
        requester_id=actor.id,
        requester_role=actor.role,
    )
    return OrderResponse.from_bundle(bundle)


@router.post(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    summary="Cancel a pending order and release its reservations",
)
async def cancel_order(
    order_id: UUID,
    service: OrderPaymentServiceDependency,
    actor: OrderActorDependency,
) -> OrderResponse:
    bundle = await service.cancel_order(
        order_id,
        requester_id=actor.id,
        requester_role=actor.role,
    )
    return OrderResponse.from_bundle(bundle)
