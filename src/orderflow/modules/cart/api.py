from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from orderflow.modules.auth.dependencies import require_roles
from orderflow.modules.auth.domain import UserRole
from orderflow.modules.auth.models import User
from orderflow.modules.cart.dependencies import get_cart_service
from orderflow.modules.cart.schemas import (
    CartItemCreateRequest,
    CartItemResponse,
    CartItemUpdateRequest,
    CartResponse,
)
from orderflow.modules.cart.service import CartService, CartView

router = APIRouter()

CartServiceDependency = Annotated[CartService, Depends(get_cart_service)]
CartCustomerDependency = Annotated[User, Depends(require_roles(UserRole.CUSTOMER))]


def cart_response(view: CartView) -> CartResponse:
    return CartResponse(
        id=view.cart.id if view.cart else None,
        items=[
            CartItemResponse(
                id=view_item.item.id,
                product_id=view_item.item.product_id,
                warehouse_id=view_item.item.warehouse_id,
                product_name=view_item.product.name,
                product_sku=view_item.product.sku,
                unit_price_minor=view_item.product.price_minor,
                quantity=view_item.item.quantity,
                line_total_minor=view_item.line_total_minor,
                currency=view_item.product.currency,
                is_available=view_item.is_available,
                created_at=view_item.item.created_at,
                updated_at=view_item.item.updated_at,
            )
            for view_item in view.items
        ],
        total_minor=view.total_minor,
        currency=view.currency,
        updated_at=view.cart.updated_at if view.cart else None,
    )


@router.get("", response_model=CartResponse, summary="Get the current customer's cart")
async def get_cart(
    service: CartServiceDependency,
    customer: CartCustomerDependency,
) -> CartResponse:
    return cart_response(await service.get_cart(customer.id))


@router.post(
    "/items",
    response_model=CartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a product from a warehouse to the cart",
)
async def add_cart_item(
    payload: CartItemCreateRequest,
    service: CartServiceDependency,
    customer: CartCustomerDependency,
) -> CartResponse:
    return cart_response(
        await service.add_item(
            customer_id=customer.id,
            product_id=payload.product_id,
            warehouse_id=payload.warehouse_id,
            quantity=payload.quantity,
        )
    )


@router.patch(
    "/items/{item_id}",
    response_model=CartResponse,
    summary="Set a cart item quantity",
)
async def update_cart_item(
    item_id: UUID,
    payload: CartItemUpdateRequest,
    service: CartServiceDependency,
    customer: CartCustomerDependency,
) -> CartResponse:
    return cart_response(
        await service.update_item(
            customer_id=customer.id,
            item_id=item_id,
            quantity=payload.quantity,
        )
    )


@router.delete(
    "/items/{item_id}",
    response_model=CartResponse,
    summary="Remove a cart item",
)
async def remove_cart_item(
    item_id: UUID,
    service: CartServiceDependency,
    customer: CartCustomerDependency,
) -> CartResponse:
    return cart_response(await service.remove_item(customer_id=customer.id, item_id=item_id))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Clear the cart")
async def clear_cart(
    service: CartServiceDependency,
    customer: CartCustomerDependency,
) -> Response:
    await service.clear(customer.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
