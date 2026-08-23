"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { cartItemsForProduct, preferredAvailability, productCartQuantity } from "@/lib/catalog";
import { formatMoney } from "@/lib/format";
import type {
  Cart,
  Product,
  ProductAvailability,
  ProductAvailabilityList,
  ProductPage,
  User,
} from "@/lib/types";

import { EmptyState, ErrorState, Icon, LoadingBlock, ProductMark } from "../ui";

export function CatalogScreen({
  user,
  requestAuth,
}: {
  user: User | null;
  requestAuth: () => void;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [cart, setCart] = useState<Cart | null>(null);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [cartLoading, setCartLoading] = useState(false);
  const [error, setError] = useState("");
  const [busyProductId, setBusyProductId] = useState("");
  const [availabilityByProduct, setAvailabilityByProduct] = useState<
    Record<string, ProductAvailability[]>
  >({});

  const loadProducts = useCallback(async (query = "") => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page_size: "100", sort_by: "name", sort_direction: "asc" });
      if (query.trim()) params.set("search", query.trim());
      const response = await apiRequest<ProductPage>(`/catalog/products?${params}`, {}, { auth: false });
      setProducts(response.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить каталог");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadProducts(""), 0);
    return () => window.clearTimeout(timer);
  }, [loadProducts]);

  const loadCart = useCallback(async () => {
    if (!user || user.role !== "customer") {
      setCart(null);
      setCartLoading(false);
      return;
    }

    setCartLoading(true);
    try {
      setCart(await apiRequest<Cart>("/cart"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить корзину");
    } finally {
      setCartLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCart(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCart]);

  async function getAvailability(productId: string): Promise<ProductAvailability[]> {
    const cached = availabilityByProduct[productId];
    if (cached) return cached;

    const response = await apiRequest<ProductAvailabilityList>(
      `/inventory/availability/${productId}`,
      {},
      { auth: false },
    );
    setAvailabilityByProduct((current) => ({ ...current, [productId]: response.items }));
    return response.items;
  }

  async function changeCartQuantity(product: Product, change: -1 | 1) {
    if (!user) {
      requestAuth();
      return;
    }
    if (user.role !== "customer") return;

    setBusyProductId(product.id);
    setError("");
    try {
      const productItems = cartItemsForProduct(cart, product.id);
      const existingItem = productItems[0];

      if (change === -1) {
        if (!existingItem) return;
        const updatedCart =
          existingItem.quantity === 1
            ? await apiRequest<Cart>(`/cart/items/${existingItem.id}`, { method: "DELETE" })
            : await apiRequest<Cart>(`/cart/items/${existingItem.id}`, {
                method: "PATCH",
                body: JSON.stringify({ quantity: existingItem.quantity - 1 }),
              });
        setCart(updatedCart);
        return;
      }

      const availability = await getAvailability(product.id);
      if (existingItem) {
        const warehouse = availability.find(
          (item) => item.warehouse_id === existingItem.warehouse_id,
        );
        if (!warehouse || existingItem.quantity >= warehouse.available) {
          setError("На выбранном складе больше нет доступного количества этого товара");
          return;
        }
        setCart(
          await apiRequest<Cart>(`/cart/items/${existingItem.id}`, {
            method: "PATCH",
            body: JSON.stringify({ quantity: existingItem.quantity + 1 }),
          }),
        );
        return;
      }

      const warehouse = preferredAvailability(availability);
      if (!warehouse) {
        setError("Товара сейчас нет в наличии");
        return;
      }
      setCart(
        await apiRequest<Cart>("/cart/items", {
          method: "POST",
          body: JSON.stringify({
            product_id: product.id,
            warehouse_id: warehouse.warehouse_id,
            quantity: 1,
          }),
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось изменить корзину");
    } finally {
      setBusyProductId("");
    }
  }

  const canBuy = !user || user.role === "customer";

  return (
    <div className="page-shell">
      <section className="page-heading catalog-heading">
        <div>
          <span className="eyebrow">Каталог OrderFlow</span>
          <h1>Товары для вашего заказа</h1>
          <p>Актуальные цены и реальные складские остатки без скрытых резервов.</p>
        </div>
        <form
          className="search-box"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            void loadProducts(search);
          }}
        >
          <Icon name="search" size={19} />
          <input
            aria-label="Поиск товаров"
            placeholder="Название или SKU"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button className="button button-primary" type="submit">
            Найти
          </button>
        </form>
      </section>

      {error ? (
        <ErrorState
          message={error}
          retry={() => {
            void loadProducts(search);
            void loadCart();
          }}
        />
      ) : null}
      {loading ? (
        <LoadingBlock label="Загружаем каталог" />
      ) : products.length === 0 ? (
        <EmptyState
          title="Товары не найдены"
          text="Измените поисковый запрос или добавьте товары через API менеджера."
        />
      ) : (
        <section className="product-grid" aria-label="Каталог товаров">
          {products.map((product) => {
            const quantity = productCartQuantity(cart, product.id);
            const controlsDisabled = cartLoading || busyProductId !== "";
            return (
              <article className="product-card" key={product.id}>
                <div className="product-visual">
                  <ProductMark name={product.name} imageUrl={product.image_url} />
                  <span className="sku-chip">{product.sku}</span>
                </div>
                <div className="product-body">
                  <h2>{product.name}</h2>
                  <p>{product.description || "Надёжный товар из каталога OrderFlow."}</p>
                  <div className="product-footer">
                    <strong>{formatMoney(product.price_minor, product.currency)}</strong>
                    {!canBuy ? (
                      <span className="manager-note">Просмотр менеджера</span>
                    ) : quantity > 0 ? (
                      <div className="catalog-quantity" aria-label={`${product.name} в корзине`}>
                        <button
                          aria-label={`Уменьшить количество ${product.name}`}
                          disabled={controlsDisabled}
                          type="button"
                          onClick={() => void changeCartQuantity(product, -1)}
                        >
                          −
                        </button>
                        <span aria-live="polite">
                          {busyProductId === product.id ? "…" : quantity}
                        </span>
                        <button
                          aria-label={`Увеличить количество ${product.name}`}
                          disabled={controlsDisabled}
                          type="button"
                          onClick={() => void changeCartQuantity(product, 1)}
                        >
                          +
                        </button>
                      </div>
                    ) : (
                      <button
                        className="button button-primary"
                        disabled={controlsDisabled}
                        type="button"
                        onClick={() => void changeCartQuantity(product, 1)}
                      >
                        <Icon name="cart" size={17} />
                        {cartLoading && user?.role === "customer"
                          ? "Загружаем…"
                          : busyProductId === product.id
                            ? "Добавляем…"
                            : "В корзину"}
                      </button>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
