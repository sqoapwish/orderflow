"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiRequest } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
import { customerVisibleOrders, orderProductSummary } from "@/lib/orders";
import type { Order, OrderPage, OrderStatus, User } from "@/lib/types";

import { EmptyState, ErrorState, LoadingBlock, StatusBadge } from "../ui";

const FILTERS: { value: "" | OrderStatus; label: string }[] = [
  { value: "", label: "Все" },
  { value: "pending_payment", label: "Ожидают оплаты" },
  { value: "paid", label: "Оплачены" },
  { value: "payment_failed", label: "Ошибки" },
  { value: "refunded", label: "Возвраты" },
  { value: "cancelled", label: "Отменены" },
];

export function OrdersScreen({ user }: { user: User | null }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [filter, setFilter] = useState<"" | OrderStatus>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const timers = useRef<number[]>([]);

  const loadOrders = useCallback(async (status: "" | OrderStatus) => {
    if (!user) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page_size: "100" });
      if (status) params.set("status", status);
      const response = await apiRequest<OrderPage>(`/orders?${params}`);
      setOrders(user.role === "customer" ? customerVisibleOrders(response.items) : response.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить заказы");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadOrders(""), 0);
    return () => window.clearTimeout(timer);
  }, [loadOrders]);

  useEffect(
    () => () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
    },
    [],
  );

  async function cancel(orderId: string) {
    setBusy(orderId);
    try {
      const updated = await apiRequest<Order>(`/orders/${orderId}/cancel`, { method: "POST" });
      setOrders((current) => current.map((order) => (order.id === orderId ? updated : order)));
      if (user?.role === "customer") {
        setNotice("Заказ отменён. Он исчезнет из списка в течение нескольких минут.");
        timers.current.push(
          window.setTimeout(
            () => setOrders((current) => current.filter((order) => order.id !== orderId)),
            2500,
          ),
          window.setTimeout(() => setNotice(""), 5500),
        );
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось отменить заказ");
    } finally {
      setBusy("");
    }
  }

  if (!user) {
    return <div className="page-shell"><EmptyState icon="orders" title="Войдите, чтобы увидеть заказы" text="История доступна только владельцу аккаунта." /></div>;
  }

  const filters = user.role === "customer"
    ? FILTERS.filter((item) => item.value !== "cancelled")
    : FILTERS;

  return (
    <div className="page-shell">
      <section className="page-heading split-heading">
        <div>
          <span className="eyebrow">История операций</span>
          <h1>{user.role === "customer" ? "Мои заказы" : "Заказы клиентов"}</h1>
          <p>Статусы отражают реальное состояние платежей и складских резервов.</p>
        </div>
        <div className="segmented" aria-label="Фильтр статуса">
          {filters.map((item) => (
            <button
              className={filter === item.value ? "segment-active" : ""}
              key={item.value || "all"}
              type="button"
              onClick={() => {
                setFilter(item.value);
                void loadOrders(item.value);
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>
      {notice ? <div className="order-notice" role="status">{notice}</div> : null}
      {error ? <ErrorState message={error} retry={() => void loadOrders(filter)} /> : null}
      {loading ? (
        <LoadingBlock label="Загружаем заказы" />
      ) : orders.length === 0 ? (
        <EmptyState icon="orders" title="Заказов пока нет" text="Новые заказы появятся здесь сразу после оформления покупки." />
      ) : (
        <section className="orders-table card">
          <div className="table-head orders-grid">
            <span>Товар</span><span>Создан</span><span>Статус</span><span>Сумма</span><span />
          </div>
          {orders.map((order) => {
            const product = orderProductSummary(order);
            return (
              <article className="table-row orders-grid" key={order.id}>
                <div className="order-product"><strong>{product.title}</strong><small>{product.detail}</small></div>
                <span>{formatDateTime(order.created_at)}</span>
                <StatusBadge status={order.status} />
                <strong>{formatMoney(order.total_minor, order.currency)}</strong>
                {order.status === "pending_payment" ? (
                  <button className="button button-secondary button-small" disabled={busy === order.id} onClick={() => void cancel(order.id)}>
                    {busy === order.id ? "Отмена…" : "Отменить"}
                  </button>
                ) : <span />}
                <details className="order-details">
                  <summary>Состав заказа</summary>
                  <div>
                    {order.items.map((item) => (
                      <p key={item.id}><span>{item.product_name} × {item.quantity}</span><strong>{formatMoney(item.line_total_minor, item.currency)}</strong></p>
                    ))}
                  </div>
                </details>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}
