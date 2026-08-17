from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.payments.dependencies import get_payment_service
from orderflow.modules.payments.domain import PaymentFilters, PaymentStatus
from orderflow.modules.payments.schemas import (
    PaymentPageResponse,
    PaymentResponse,
    PaymentSessionCreate,
    WebhookResponse,
)
from orderflow.modules.payments.service import PaymentService

router = APIRouter()

PaymentServiceDependency = Annotated[PaymentService, Depends(get_payment_service)]
PaymentActorDependency = Annotated[
    User,
    Depends(require_roles(UserRole.CUSTOMER, UserRole.MANAGER, UserRole.ADMIN)),
]
PaymentCustomerDependency = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]
PaymentManagerDependency = Annotated[
    User,
    Depends(require_roles(UserRole.MANAGER, UserRole.ADMIN)),
]


@router.post(
    "/sessions",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an idempotent Mock Payment session",
)
async def create_payment_session(
    payload: PaymentSessionCreate,
    response: Response,
    service: PaymentServiceDependency,
    customer: PaymentCustomerDependency,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> PaymentResponse:
    result = await service.create_session(
        order_id=payload.order_id,
        customer_id=customer.id,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return PaymentResponse.from_bundle(result.bundle)


@router.get("", response_model=PaymentPageResponse, summary="List visible payments")
async def list_payments(
    service: PaymentServiceDependency,
    actor: PaymentActorDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    customer_id: UUID | None = None,
    payment_status: Annotated[PaymentStatus | None, Query(alias="status")] = None,
) -> PaymentPageResponse:
    result = await service.list_payments(
        PaymentFilters(
            page=page,
            page_size=page_size,
            customer_id=customer_id,
            status=payment_status,
        ),
        requester_id=actor.id,
        requester_role=actor.role,
    )
    return PaymentPageResponse(
        items=[PaymentResponse.from_bundle(bundle) for bundle in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get("/{payment_id}", response_model=PaymentResponse, summary="Get a visible payment")
async def get_payment(
    payment_id: UUID,
    service: PaymentServiceDependency,
    actor: PaymentActorDependency,
) -> PaymentResponse:
    bundle = await service.get_payment(
        payment_id,
        requester_id=actor.id,
        requester_role=actor.role,
    )
    return PaymentResponse.from_bundle(bundle)


@router.post(
    "/{payment_id}/refunds",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an idempotent full refund",
)
async def refund_payment(
    payment_id: UUID,
    response: Response,
    service: PaymentServiceDependency,
    actor: PaymentManagerDependency,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=128),
    ],
) -> PaymentResponse:
    result = await service.refund_payment(
        payment_id,
        actor_id=actor.id,
        actor_role=actor.role,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    return PaymentResponse.from_bundle(result.bundle)


@router.post(
    "/webhooks/mock",
    response_model=WebhookResponse,
    summary="Process a signed Mock Payment webhook",
)
async def mock_payment_webhook(
    request: Request,
    service: PaymentServiceDependency,
    timestamp: Annotated[int, Header(alias="X-Payment-Timestamp")],
    signature: Annotated[str, Header(alias="X-Payment-Signature")],
) -> WebhookResponse:
    result = await service.handle_webhook(
        raw_body=await request.body(),
        timestamp=timestamp,
        signature=signature,
    )
    return WebhookResponse(status=result.status)
