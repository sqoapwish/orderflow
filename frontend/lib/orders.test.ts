import { describe, expect, it } from "vitest";

import { customerVisibleOrders, orderProductSummary } from "./orders";
import type { Order, OrderItem } from "./types";

function item(name: string, quantity: number): OrderItem {
  return {
    id: `${name}-${quantity}`,
    product_id: `${name}-product`,
    warehouse_id: "warehouse-1",
    product_name: name,
    product_sku: name.toUpperCase(),
    unit_price_minor: 100,
    quantity,
    line_total_minor: quantity * 100,
    currency: "RUB",
  };
}

function order(status: Order["status"], items: OrderItem[]): Order {
  return {
    id: `${status}-order`,
    order_number: `OF-${status}`,
    customer_id: "customer-1",
    status,
    total_minor: items.reduce((total, value) => total + value.line_total_minor, 0),
    currency: "RUB",
    items,
    created_at: "2026-08-23T10:00:00Z",
    updated_at: "2026-08-23T10:00:00Z",
  };
}

describe("order presentation helpers", () => {
  it("uses the product name instead of a technical order key", () => {
    expect(orderProductSummary(order("pending_payment", [item("Ежедневник Focus", 1)]))).toEqual({
      title: "Ежедневник Focus",
      detail: "1 шт.",
    });
  });

  it("summarizes orders with several products", () => {
    expect(orderProductSummary(order("paid", [item("Ежедневник", 2), item("Рюкзак", 1)]))).toEqual({
      title: "Ежедневник",
      detail: "3 шт. · ещё 1 поз.",
    });
  });

  it("hides cancelled orders from the customer list", () => {
    expect(
      customerVisibleOrders([
        order("pending_payment", [item("Ежедневник", 1)]),
        order("cancelled", [item("Рюкзак", 1)]),
      ]),
    ).toHaveLength(1);
  });
});
