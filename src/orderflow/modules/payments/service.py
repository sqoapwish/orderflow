import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from orderflow.modules.auth.domain import UserRole
from orderflow.modules.orders.domain import OrderStatus, can_transition_order
from orderflow.modules.orders.errors import (
    OrderNotFoundError,
    OrderStateConflictError,
)
from orderflow.modules.orders.models import OrderItem
from orderflow.modules.orders.repository import OrderBundle, OrderRepositoryProtocol
from orderflow.modules.outbox.domain import OutboxEventType
from orderflow.modules.outbox.repository import OutboxWriterProtocol
from orderflow.modules.outbox.service import build_outbox_event
from orderflow.modules.payments.domain import (
    PaymentEventType,
    PaymentFilters,
    PaymentStatus,
    RefundStatus,
    WebhookOutcome,
)
from orderflow.modules.payments.errors import (
    InvalidPaymentIdempotencyKeyError,
    InvalidWebhookPayloadError,
    InvalidWebhookSignatureError,
    PaymentAmountConflictError,
    PaymentIdempotencyConflictError,
    PaymentNotFoundError,
    PaymentStateConflictError,
    PaymentWriteConflictError,
    StaleWebhookError,
    WebhookEventConflictError,
)
from orderflow.modules.payments.models import Payment, PaymentRefund, PaymentWebhookEvent
from orderflow.modules.payments.provider import MockPaymentProvider
from orderflow.modules.payments.repository import PaymentBundle, PaymentRepositoryProtocol
from orderflow.modules.payments.schemas import MockWebhookPayload


class PaymentInventoryProtocol(Protocol):
    async def release_reservation(
        self,
        reservation_id: UUID,
        *,
        actor_id: UUID,
        commit: bool = True,
    ) -> object: ...

    async def consume_reservation(
        self,
        reservation_id: UUID,
        *,
        actor_id: UUID,
        commit: bool = True,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class PaymentMutationResult:
    bundle: PaymentBundle
    created: bool


@dataclass(frozen=True, slots=True)
class PaymentPage:
    items: list[PaymentBundle]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class WebhookResult:
    status: str


class PaymentService:
    def __init__(
        self,
        repository: PaymentRepositoryProtocol,
        orders: OrderRepositoryProtocol,
        inventory: PaymentInventoryProtocol,
        provider: MockPaymentProvider,
        outbox: OutboxWriterProtocol,
        *,
        webhook_tolerance_seconds: int,
    ) -> None:
        self._repository = repository
        self._orders = orders
        self._inventory = inventory
        self._provider = provider
        self._outbox = outbox
        self._webhook_tolerance_seconds = webhook_tolerance_seconds

    async def create_session(
        self,
        *,
        order_id: UUID,
        customer_id: UUID,
        idempotency_key: str,
    ) -> PaymentMutationResult:
        key = self._validate_key(idempotency_key)
        try:
            await self._repository.acquire_session_lock(customer_id, key)
            existing = await self._repository.get_by_idempotency_key(customer_id, key)
            if existing is not None:
                if existing.payment.order_id != order_id:
                    raise PaymentIdempotencyConflictError
                await self._repository.commit()
                return PaymentMutationResult(bundle=existing, created=False)

            order_payment = await self._repository.get_by_order(order_id)
            if order_payment is not None:
                if order_payment.payment.customer_id != customer_id:
                    raise OrderNotFoundError
                await self._repository.commit()
                return PaymentMutationResult(bundle=order_payment, created=False)

            order_bundle = await self._orders.get(order_id, for_update=True)
            if order_bundle is None or order_bundle.order.customer_id != customer_id:
                raise OrderNotFoundError
            if order_bundle.order.status is not OrderStatus.PENDING_PAYMENT:
                raise PaymentStateConflictError(
                    current=order_bundle.order.status,
                    operation="create a session",
                )

            order_payment = await self._repository.get_by_order(order_id)
            if order_payment is not None:
                await self._repository.commit()
                return PaymentMutationResult(bundle=order_payment, created=False)

            provider_session = self._provider.create_session()
            payment = Payment(
                id=uuid4(),
                order_id=order_bundle.order.id,
                customer_id=customer_id,
                idempotency_key=key,
                provider=self._provider.name,
                provider_payment_id=provider_session.provider_payment_id,
                checkout_url=provider_session.checkout_url,
                status=PaymentStatus.PENDING,
                amount_minor=order_bundle.order.total_minor,
                currency=order_bundle.order.currency,
                expires_at=provider_session.expires_at,
            )
            self._repository.add_payment(payment)
            await self._repository.flush()
            await self._repository.commit()
            return PaymentMutationResult(
                bundle=PaymentBundle(payment=payment, refund=None),
                created=True,
            )
        except IntegrityError:
            await self._repository.rollback()
            raise PaymentWriteConflictError from None
        except Exception:
            await self._repository.rollback()
            raise

    async def list_payments(
        self,
        filters: PaymentFilters,
        *,
        requester_id: UUID,
        requester_role: UserRole,
    ) -> PaymentPage:
        effective_filters = filters
        if requester_role is UserRole.CUSTOMER:
            effective_filters = PaymentFilters(
                page=filters.page,
                page_size=filters.page_size,
                customer_id=requester_id,
                status=filters.status,
            )
        items, total = await self._repository.list_payments(effective_filters)
        return PaymentPage(
            items=items,
            total=total,
            page=filters.page,
            page_size=filters.page_size,
            total_pages=ceil(total / filters.page_size) if total else 0,
        )

    async def get_payment(
        self,
        payment_id: UUID,
        *,
        requester_id: UUID,
        requester_role: UserRole,
    ) -> PaymentBundle:
        bundle = await self._repository.get(payment_id)
        if bundle is None or (
            requester_role is UserRole.CUSTOMER and bundle.payment.customer_id != requester_id
        ):
            raise PaymentNotFoundError
        return bundle

    async def cancel_order(
        self,
        order_id: UUID,
        *,
        requester_id: UUID,
        requester_role: UserRole,
    ) -> OrderBundle:
        try:
            payment_bundle = await self._repository.get_by_order(order_id, for_update=True)
            order_bundle = await self._orders.get(order_id, for_update=True)
            if order_bundle is None or (
                requester_role is UserRole.CUSTOMER
                and order_bundle.order.customer_id != requester_id
            ):
                raise OrderNotFoundError
            if order_bundle.order.status is OrderStatus.CANCELLED:
                await self._repository.commit()
                return order_bundle
            self._transition_order(order_bundle, OrderStatus.CANCELLED)

            if payment_bundle is not None:
                payment = payment_bundle.payment
                if payment.status is not PaymentStatus.PENDING:
                    raise PaymentStateConflictError(
                        current=payment.status,
                        operation="cancel the order",
                    )
                payment.status = PaymentStatus.CANCELLED
                payment.processed_at = datetime.now(UTC)
            await self._release_reservations(order_bundle)
            self._outbox.add(
                build_outbox_event(
                    event_type=OutboxEventType.ORDER_CANCELLED,
                    aggregate_type="order",
                    aggregate_id=order_bundle.order.id,
                    deduplication_key=f"order:{order_bundle.order.id}:cancelled",
                    payload={
                        "order_id": str(order_bundle.order.id),
                        "customer_id": str(order_bundle.order.customer_id),
                        "status": order_bundle.order.status.value,
                        "payment_id": (
                            str(payment_bundle.payment.id) if payment_bundle is not None else None
                        ),
                    },
                )
            )
            await self._repository.flush()
            await self._repository.commit()
            return order_bundle
        except IntegrityError:
            await self._repository.rollback()
            raise PaymentWriteConflictError from None
        except Exception:
            await self._repository.rollback()
            raise

    async def refund_payment(
        self,
        payment_id: UUID,
        *,
        actor_id: UUID,
        idempotency_key: str,
    ) -> PaymentMutationResult:
        key = self._validate_key(idempotency_key)
        try:
            await self._repository.acquire_refund_lock(payment_id)
            existing_refund = await self._repository.get_refund_by_payment(payment_id)
            if existing_refund is not None:
                payment_bundle = await self._repository.get(payment_id)
                if payment_bundle is None:
                    raise PaymentNotFoundError
                await self._repository.commit()
                return PaymentMutationResult(bundle=payment_bundle, created=False)

            payment_bundle = await self._repository.get(payment_id, for_update=True)
            if payment_bundle is None:
                raise PaymentNotFoundError
            payment = payment_bundle.payment
            if payment.status is not PaymentStatus.SUCCEEDED:
                raise PaymentStateConflictError(
                    current=payment.status,
                    operation="refund it",
                )
            order_bundle = await self._orders.get(payment.order_id, for_update=True)
            if order_bundle is None:
                raise OrderNotFoundError
            self._transition_order(order_bundle, OrderStatus.REFUNDED)

            refund = PaymentRefund(
                id=uuid4(),
                payment_id=payment.id,
                idempotency_key=key,
                provider_refund_id=self._provider.create_refund_id(),
                amount_minor=payment.amount_minor,
                currency=payment.currency,
                status=RefundStatus.SUCCEEDED,
                created_by_user_id=actor_id,
            )
            self._repository.add_refund(refund)
            payment.status = PaymentStatus.REFUNDED
            payment.processed_at = datetime.now(UTC)
            self._outbox.add(
                build_outbox_event(
                    event_type=OutboxEventType.PAYMENT_REFUNDED,
                    aggregate_type="payment",
                    aggregate_id=payment.id,
                    deduplication_key=f"payment:{payment.id}:refunded",
                    payload={
                        "payment_id": str(payment.id),
                        "order_id": str(payment.order_id),
                        "customer_id": str(payment.customer_id),
                        "refund_id": str(refund.id),
                        "amount_minor": refund.amount_minor,
                        "currency": refund.currency,
                        "status": payment.status.value,
                        "actor_id": str(actor_id),
                    },
                )
            )
            await self._repository.flush()
            await self._repository.commit()
            return PaymentMutationResult(
                bundle=PaymentBundle(payment=payment, refund=refund),
                created=True,
            )
        except IntegrityError:
            await self._repository.rollback()
            raise PaymentWriteConflictError from None
        except Exception:
            await self._repository.rollback()
            raise

    async def handle_webhook(
        self,
        *,
        raw_body: bytes,
        timestamp: int,
        signature: str,
    ) -> WebhookResult:
        self._verify_webhook(raw_body=raw_body, timestamp=timestamp, signature=signature)
        try:
            payload = MockWebhookPayload.model_validate_json(raw_body)
        except ValidationError:
            raise InvalidWebhookPayloadError from None
        payload_hash = hashlib.sha256(raw_body).hexdigest()

        try:
            await self._repository.acquire_event_lock(payload.event_id)
            existing_event = await self._repository.get_event(payload.event_id)
            if existing_event is not None:
                if existing_event.payload_hash != payload_hash:
                    raise WebhookEventConflictError
                await self._repository.commit()
                return WebhookResult(status="duplicate")

            payment_bundle = await self._repository.get_by_provider_id(
                payload.provider_payment_id,
                for_update=True,
            )
            if payment_bundle is None:
                raise PaymentNotFoundError
            payment = payment_bundle.payment
            if payment.amount_minor != payload.amount_minor or payment.currency != payload.currency:
                raise PaymentAmountConflictError
            order_bundle = await self._orders.get(payment.order_id, for_update=True)
            if order_bundle is None:
                raise OrderNotFoundError

            outcome = await self._apply_webhook_event(payload, payment, order_bundle)
            self._repository.add_event(
                PaymentWebhookEvent(
                    id=uuid4(),
                    provider_event_id=payload.event_id,
                    payment_id=payment.id,
                    event_type=payload.type,
                    payload_hash=payload_hash,
                    outcome=outcome,
                )
            )
            if outcome is WebhookOutcome.PROCESSED:
                event_type = (
                    OutboxEventType.PAYMENT_SUCCEEDED
                    if payload.type is PaymentEventType.SUCCEEDED
                    else OutboxEventType.PAYMENT_FAILED
                )
                self._outbox.add(
                    build_outbox_event(
                        event_type=event_type,
                        aggregate_type="payment",
                        aggregate_id=payment.id,
                        deduplication_key=f"payment:{payment.id}:{event_type.value}",
                        payload={
                            "payment_id": str(payment.id),
                            "order_id": str(payment.order_id),
                            "customer_id": str(payment.customer_id),
                            "amount_minor": payment.amount_minor,
                            "currency": payment.currency,
                            "status": payment.status.value,
                            "order_status": order_bundle.order.status.value,
                            "failure_code": payment.failure_code,
                            "provider_event_id": payload.event_id,
                        },
                    )
                )
            await self._repository.flush()
            await self._repository.commit()
            return WebhookResult(status=outcome.value)
        except IntegrityError:
            await self._repository.rollback()
            raise PaymentWriteConflictError from None
        except Exception:
            await self._repository.rollback()
            raise

    async def _apply_webhook_event(
        self,
        payload: MockWebhookPayload,
        payment: Payment,
        order_bundle: OrderBundle,
    ) -> WebhookOutcome:
        if payload.type is PaymentEventType.SUCCEEDED:
            if (
                payment.status is not PaymentStatus.PENDING
                or order_bundle.order.status is not OrderStatus.PENDING_PAYMENT
            ):
                return WebhookOutcome.IGNORED
            await self._consume_reservations(order_bundle)
            self._transition_order(order_bundle, OrderStatus.PAID)
            payment.status = PaymentStatus.SUCCEEDED
            payment.failure_code = None
            payment.processed_at = datetime.now(UTC)
            return WebhookOutcome.PROCESSED

        if (
            payment.status is not PaymentStatus.PENDING
            or order_bundle.order.status is not OrderStatus.PENDING_PAYMENT
        ):
            return WebhookOutcome.IGNORED
        await self._release_reservations(order_bundle)
        self._transition_order(order_bundle, OrderStatus.PAYMENT_FAILED)
        payment.status = PaymentStatus.FAILED
        payment.failure_code = payload.failure_code or "mock_payment_failed"
        payment.processed_at = datetime.now(UTC)
        return WebhookOutcome.PROCESSED

    async def _consume_reservations(self, order_bundle: OrderBundle) -> None:
        for item in self._ordered_items(order_bundle):
            await self._inventory.consume_reservation(
                item.reservation_id,
                actor_id=order_bundle.order.customer_id,
                commit=False,
            )

    async def _release_reservations(self, order_bundle: OrderBundle) -> None:
        for item in self._ordered_items(order_bundle):
            await self._inventory.release_reservation(
                item.reservation_id,
                actor_id=order_bundle.order.customer_id,
                commit=False,
            )

    @staticmethod
    def _ordered_items(order_bundle: OrderBundle) -> list[OrderItem]:
        return sorted(
            order_bundle.items,
            key=lambda item: (item.warehouse_id.int, item.product_id.int, item.id.int),
        )

    @staticmethod
    def _transition_order(order_bundle: OrderBundle, target: OrderStatus) -> None:
        current = order_bundle.order.status
        if not can_transition_order(current, target):
            raise OrderStateConflictError(current=current, target=target)
        order_bundle.order.status = target

    @staticmethod
    def _validate_key(idempotency_key: str) -> str:
        key = idempotency_key.strip()
        if not key or len(key) > 128:
            raise InvalidPaymentIdempotencyKeyError
        return key

    def _verify_webhook(self, *, raw_body: bytes, timestamp: int, signature: str) -> None:
        now_timestamp = int(datetime.now(UTC).timestamp())
        if abs(now_timestamp - timestamp) > self._webhook_tolerance_seconds:
            raise StaleWebhookError
        if not self._provider.verify_webhook(
            timestamp=timestamp,
            body=raw_body,
            signature=signature,
        ):
            raise InvalidWebhookSignatureError
