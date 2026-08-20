"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type {
  Cart,
  Product,
  ProductAvailability,
  ProductAvailabilityList,
  ProductPage,
  User,
} from "@/lib/types";

import type { Screen } from "../app-shell";
import { EmptyState, ErrorState, Icon, LoadingBlock, ProductMark } from "../ui";

export function CatalogScreen({
  user,
  requestAuth,
  onNavigate,
}: {
  user: User | null;
  requestAuth: () => void;
  onNavigate: (screen: Screen) => void;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Product | null>(null);
  const [availability, setAvailability] = useState<ProductAvailability[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [adding, setAdding] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);

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

  async function openProduct(product: Product) {
    if (!user) {
      requestAuth();
      return;
    }
    if (user.role !== "customer") return;
    setSelected(product);
    setModalLoading(true);
    setQuantity(1);
    setAvailability([]);
    setWarehouseId("");
    try {
      const response = await apiRequest<ProductAvailabilityList>(
        `/inventory/availability/${product.id}`,
        {},
        { auth: false },
      );
      setAvailability(response.items);
      setWarehouseId(response.items[0]?.warehouse_id ?? "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить остатки");
      setSelected(null);
    } finally {
      setModalLoading(false);
    }
  }

  async function addToCart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || !warehouseId) return;
    setAdding(true);
    try {
      await apiRequest<Cart>("/cart/items", {
        method: "POST",
        body: JSON.stringify({ product_id: selected.id, warehouse_id: warehouseId, quantity }),
      });
      setSelected(null);
      onNavigate("cart");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось добавить товар");
    } finally {
      setAdding(false);
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

      {error ? <ErrorState message={error} retry={() => void loadProducts(search)} /> : null}
      {loading ? (
        <LoadingBlock label="Загружаем каталог" />
      ) : products.length === 0 ? (
        <EmptyState
          title="Товары не найдены"
          text="Измените поисковый запрос или добавьте товары через API менеджера."
        />
      ) : (
        <section className="product-grid" aria-label="Каталог товаров">
          {products.map((product) => (
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
                  {canBuy ? (
                    <button className="button button-primary" type="button" onClick={() => void openProduct(product)}>
                      <Icon name="cart" size={17} />
                      В корзину
                    </button>
                  ) : (
                    <span className="manager-note">Просмотр менеджера</span>
                  )}
                </div>
              </div>
            </article>
          ))}
        </section>
      )}

      {selected ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setSelected(null)}>
          <section
            aria-labelledby="product-dialog-title"
            aria-modal="true"
            className="product-dialog"
            role="dialog"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button className="icon-button modal-close" aria-label="Закрыть" onClick={() => setSelected(null)}>
              <Icon name="x" />
            </button>
            <div className="dialog-product-row">
              <ProductMark name={selected.name} imageUrl={selected.image_url} />
              <div>
                <span className="eyebrow">{selected.sku}</span>
                <h2 id="product-dialog-title">{selected.name}</h2>
                <strong>{formatMoney(selected.price_minor, selected.currency)}</strong>
              </div>
            </div>
            {modalLoading ? (
              <LoadingBlock label="Проверяем остатки" />
            ) : availability.length === 0 ? (
              <EmptyState
                icon="warehouse"
                title="Нет в наличии"
                text="На активных складах сейчас нет доступного количества."
              />
            ) : (
              <form className="add-form" onSubmit={addToCart}>
                <label>
                  Склад
                  <select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)}>
                    {availability.map((item) => (
                      <option key={item.warehouse_id} value={item.warehouse_id}>
                        {item.warehouse_name} · доступно {item.available}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Количество
                  <input
                    min="1"
                    max={availability.find((item) => item.warehouse_id === warehouseId)?.available ?? 1}
                    type="number"
                    value={quantity}
                    onChange={(event) => setQuantity(Number(event.target.value))}
                  />
                </label>
                <button className="button button-primary button-full" disabled={adding} type="submit">
                  {adding ? "Добавляем…" : "Добавить в корзину"}
                </button>
              </form>
            )}
          </section>
        </div>
      ) : null}
    </div>
  );
}
