import { describe, expect, it } from "vitest";

import { chartPoints, formatMoney, orderStatusLabel } from "./format";

describe("format helpers", () => {
  it("formats minor money units", () => {
    expect(formatMoney(123_456, "RUB")).toContain("1 234,56");
  });

  it("translates an order status", () => {
    expect(orderStatusLabel("pending_payment")).toBe("Ожидает оплаты");
  });

  it("builds deterministic chart points", () => {
    expect(chartPoints([0, 5, 10], 100, 50)).toBe("0.00,50.00 50.00,25.00 100.00,0.00");
    expect(chartPoints([], 100, 50)).toBe("");
  });
});
