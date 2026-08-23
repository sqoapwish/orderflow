import type { Order } from "./types";

export interface OrderProductSummary {
  title: string;
  detail: string;
}

export function orderProductSummary(order: Order): OrderProductSummary {
  const firstItem = order.items[0];
  if (!firstItem) return { title: "Заказ без товаров", detail: "0 шт." };

  const totalQuantity = order.items.reduce((total, item) => total + item.quantity, 0);
  const remainingProducts = order.items.length - 1;
  return {
    title: firstItem.product_name,
    detail:
      remainingProducts > 0
        ? `${totalQuantity} шт. · ещё ${remainingProducts} поз.`
        : `${totalQuantity} шт.`,
  };
}

export function customerVisibleOrders(orders: Order[]): Order[] {
  return orders.filter((order) => order.status !== "cancelled");
}
