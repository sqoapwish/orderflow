import { describe, expect, it } from "vitest";

import { cartItemsForProduct, preferredAvailability, productCartQuantity } from "./catalog";
import type { Cart, ProductAvailability } from "./types";

const cart: Cart = {
  id: "cart-1",
  items: [
    {
      id: "item-1",
      product_id: "product-1",
      warehouse_id: "warehouse-1",
      product_name: "Ежедневник Focus",
      product_sku: "DEMO-PLANNER",
      unit_price_minor: 149_000,
      quantity: 2,
      line_total_minor: 298_000,
      currency: "RUB",
      is_available: true,
      created_at: "2026-08-23T10:00:00Z",
      updated_at: "2026-08-23T10:00:00Z",
    },
    {
      id: "item-2",
      product_id: "product-1",
      warehouse_id: "warehouse-2",
      product_name: "Ежедневник Focus",
      product_sku: "DEMO-PLANNER",
      unit_price_minor: 149_000,
      quantity: 1,
      line_total_minor: 149_000,
      currency: "RUB",
      is_available: true,
      created_at: "2026-08-23T10:00:00Z",
      updated_at: "2026-08-23T10:00:00Z",
    },
  ],
  total_minor: 447_000,
  currency: "RUB",
  updated_at: "2026-08-23T10:00:00Z",
};

describe("catalog cart helpers", () => {
  it("finds every cart line for a product", () => {
    expect(cartItemsForProduct(cart, "product-1")).toHaveLength(2);
    expect(cartItemsForProduct(cart, "missing")).toEqual([]);
  });

  it("sums a product quantity across warehouses", () => {
    expect(productCartQuantity(cart, "product-1")).toBe(3);
    expect(productCartQuantity(null, "product-1")).toBe(0);
  });

  it("selects the warehouse with the greatest positive availability", () => {
    const availability: ProductAvailability[] = [
      { warehouse_id: "one", warehouse_name: "Первый", warehouse_code: "ONE", available: 0 },
      { warehouse_id: "two", warehouse_name: "Второй", warehouse_code: "TWO", available: 12 },
      { warehouse_id: "three", warehouse_name: "Третий", warehouse_code: "THREE", available: 8 },
    ];

    expect(preferredAvailability(availability)?.warehouse_id).toBe("two");
    expect(preferredAvailability([])).toBeNull();
  });
});
