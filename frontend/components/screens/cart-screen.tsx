"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { Cart, CartItem, Order, Payment, User } from "@/lib/types";

import type { Screen } from "../app-shell";
import { EmptyState, ErrorState, Icon, LoadingBlock, ProductMark } from "../ui";

export function CartScreen({
  user,
  onNavigate,
}: {
  user: User | null;
  onNavigate: (screen: Screen) => void;
}) {
  const [cart, setCart] = useState<Cart | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyItem, setBusyItem] = useState("");
  const [checkingOut, setCheckingOut] = useState(false);
  const [error, setError] = useState("");
  const [payment, setPayment] = useState<Payment | null>(null);

  const loadCart = useCallback(async () => {
    if (!user || user.role !== "customer") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      setCart(await apiRequest<Cart>("/cart"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить корзину");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadCart(), 0);
    return () => window.clearTimeout(timer);
  }, [loadCart]);

  async function updateItem(item: CartItem, quantity: number) {
    if (quantity < 1 || quantity > 1000) return;
    setBusyItem(item.id);
    try {
      setCart(
        await apiRequest<Cart>(`/cart/items/${item.id}`, {
          method: "PATCH",
          body: JSON.stringify({ quantity }),
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось изменить количество");
    } finally {
      setBusyItem("");
    }
  }

  async function removeItem(itemId: string) {
    setBusyItem(itemId);
    try {
      setCart(await apiRequest<Cart>(`/cart/items/${itemId}`, { method: "DELETE" }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось удалить товар");
    } finally {
      setBusyItem("");
    }
  }

  async function checkout() {
    setCheckingOut(true);
    setError("");
    try {
      const order = await apiRequest<Order>("/orders/checkout", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      const createdPayment = await apiRequest<Payment>("/payments/sessions", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ order_id: order.id }),
      });
      setPayment(createdPayment);
      setCart({ id: null, items: [], total_minor: null, currency: null, updated_at: null });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось оформить заказ");
    } finally {
      setCheckingOut(false);
    }
  }

  if (!user || user.role !== "customer") {
    return (
      <div className="page-shell">
        <EmptyState
          icon="cart"
          title="Корзина доступна покупателю"
          text="Войдите под аккаунтом с ролью customer, чтобы оформить заказ."
          action={<button className="button button-primary" onClick={() => onNavigate("catalog")}>Открыть каталог</button>}
        />
      </div>
    );
  }

  return (
    <div className="page-shell narrow-shell">
      <section className="page-heading">
        <div>
          <span className="eyebrow">Ваш выбор</span>
          <h1>Корзина</h1>
          <p>Перед оформлением ещё раз проверим цену и доступный остаток.</p>
        </div>
      </section>
      {error ? <ErrorState message={error} retry={() => void loadCart()} /> : null}
      {payment ? (
        <section className="success-panel">
          <span className="success-icon"><Icon name="check" size={26} /></span>
          <div>
            <span className="eyebrow">Заказ создан</span>
            <h2>Платёжная сессия готова</h2>
            <p>
              Mock Provider ожидает событие оплаты. Идентификатор: <code>{payment.provider_payment_id}</code>
            </p>
          </div>
          <button className="button button-primary" type="button" onClick={() => onNavigate("orders")}>
            Мои заказы
          </button>
        </section>
      ) : null}
      {loading ? (
        <LoadingBlock label="Загружаем корзину" />
      ) : !cart || cart.items.length === 0 ? (
        <EmptyState
          icon="cart"
          title="Корзина пока пуста"
          text="Выберите товары в каталоге — доступный склад подставится при добавлении."
          action={<button className="button button-primary" onClick={() => onNavigate("catalog")}>Перейти к товарам</button>}
        />
      ) : (
        <div className="cart-layout">
          <section className="cart-list card">
            {cart.items.map((item) => (
              <article className="cart-row" key={item.id}>
                <ProductMark name={item.product_name} />
                <div className="cart-product">
                  <span className="eyebrow">{item.product_sku}</span>
                  <h2>{item.product_name}</h2>
                  <span>{formatMoney(item.unit_price_minor, item.currency)} за шт.</span>
                </div>
                <div className="quantity-control" aria-label={`Количество ${item.product_name}`}>
                  <button disabled={busyItem === item.id || item.quantity <= 1} onClick={() => void updateItem(item, item.quantity - 1)}>−</button>
                  <span>{item.quantity}</span>
                  <button disabled={busyItem === item.id} onClick={() => void updateItem(item, item.quantity + 1)}>+</button>
                </div>
                <strong>{formatMoney(item.line_total_minor, item.currency)}</strong>
                <button className="icon-button danger" aria-label={`Удалить ${item.product_name}`} onClick={() => void removeItem(item.id)}>
                  <Icon name="x" />
                </button>
              </article>
            ))}
          </section>
          <aside className="cart-summary card">
            <span className="eyebrow">Итого</span>
            <div className="summary-line"><span>Товаров</span><strong>{cart.items.reduce((sum, item) => sum + item.quantity, 0)}</strong></div>
            <div className="summary-total"><span>К оплате</span><strong>{formatMoney(cart.total_minor ?? 0, cart.currency ?? "RUB")}</strong></div>
            <button
              className="button button-primary button-full"
              disabled={checkingOut || cart.items.some((item) => !item.is_available)}
              onClick={() => void checkout()}
            >
              {checkingOut ? "Оформляем…" : "Оформить заказ"}
            </button>
            <p className="summary-help">Заказ и складские резервы создаются одной транзакцией.</p>
          </aside>
        </div>
      )}
    </div>
  );
}
