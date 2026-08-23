import type { Cart, CartItem, ProductAvailability } from "./types";

export function cartItemsForProduct(cart: Cart | null, productId: string): CartItem[] {
  return cart?.items.filter((item) => item.product_id === productId) ?? [];
}

export function productCartQuantity(cart: Cart | null, productId: string): number {
  return cartItemsForProduct(cart, productId).reduce((total, item) => total + item.quantity, 0);
}

export function preferredAvailability(items: ProductAvailability[]): ProductAvailability | null {
  return items.reduce<ProductAvailability | null>((best, item) => {
    if (item.available <= 0) return best;
    if (!best || item.available > best.available) return item;
    return best;
  }, null);
}
