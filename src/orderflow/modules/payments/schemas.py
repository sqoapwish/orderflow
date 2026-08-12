from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from orderflow.modules.payments.domain import (
    PaymentEventType,
    PaymentStatus,
    RefundStatus,
)
from orderflow.modules.payments.repository import PaymentBundle


class PaymentSessionCreate(BaseModel):
    order_id: UUID


class MockWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    type: PaymentEventType
    provider_payment_id: str = Field(min_length=1, max_length=64)
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    failure_code: str | None = Field(default=None, min_length=1, max_length=64)


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    provider_refund_id: str
    amount_minor: int
    currency: str
    status: RefundStatus
    created_by_user_id: UUID
    created_at: datetime


class PaymentResponse(BaseModel):
    id: UUID
    order_id: UUID
    customer_id: UUID
    provider: str
    provider_payment_id: str
    checkout_url: str
    status: PaymentStatus
    amount_minor: int
    currency: str
    failure_code: str | None
    expires_at: datetime
    processed_at: datetime | None
    refund: RefundResponse | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_bundle(cls, bundle: PaymentBundle) -> "PaymentResponse":
        payment = bundle.payment
        refund = bundle.refund
        return cls(
            id=payment.id,
            order_id=payment.order_id,
            customer_id=payment.customer_id,
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            checkout_url=payment.checkout_url,
            status=payment.status,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            failure_code=payment.failure_code,
            expires_at=payment.expires_at,
            processed_at=payment.processed_at,
            refund=(
                RefundResponse(
                    id=refund.id,
                    payment_id=refund.payment_id,
                    provider_refund_id=refund.provider_refund_id,
                    amount_minor=refund.amount_minor,
                    currency=refund.currency,
                    status=refund.status,
                    created_by_user_id=refund.created_by_user_id,
                    created_at=refund.created_at,
                )
                if refund is not None
                else None
            ),
            created_at=payment.created_at,
            updated_at=payment.updated_at,
        )


class PaymentPageResponse(BaseModel):
    items: list[PaymentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class WebhookResponse(BaseModel):
    status: str
