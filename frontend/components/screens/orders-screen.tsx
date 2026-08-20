"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { formatDateTime, formatMoney } from "@/lib/format";
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
      setOrders(response.items);
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

  async function cancel(orderId: string) {
    setBusy(orderId);
    try {
      const updated = await apiRequest<Order>(`/orders/${orderId}/cancel`, { method: "POST" });
      setOrders((current) => current.map((order) => (order.id === orderId ? updated : order)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось отменить заказ");
    } finally {
      setBusy("");
    }
  }

  if (!user) {
    return <div className="page-shell"><EmptyState icon="orders" title="Войдите, чтобы увидеть заказы" text="История доступна только владельцу аккаунта." /></div>;
  }

  return (
    <div className="page-shell">
      <section className="page-heading split-heading">
        <div>
          <span className="eyebrow">История операций</span>
          <h1>{user.role === "customer" ? "Мои заказы" : "Заказы клиентов"}</h1>
          <p>Статусы отражают реальное состояние платежей и складских резервов.</p>
        </div>
        <div className="segmented" aria-label="Фильтр статуса">
          {FILTERS.map((item) => (
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
      {error ? <ErrorState message={error} retry={() => void loadOrders(filter)} /> : null}
      {loading ? (
        <LoadingBlock label="Загружаем заказы" />
      ) : orders.length === 0 ? (
        <EmptyState icon="orders" title="Заказов пока нет" text="Новые заказы появятся здесь сразу после checkout." />
      ) : (
        <section className="orders-table card">
          <div className="table-head orders-grid">
            <span>Заказ</span><span>Создан</span><span>Позиции</span><span>Статус</span><span>Сумма</span><span />
          </div>
          {orders.map((order) => (
            <article className="table-row orders-grid" key={order.id}>
              <div><strong>{order.order_number}</strong><small>{order.id.slice(0, 8)}</small></div>
              <span>{formatDateTime(order.created_at)}</span>
              <span>{order.items.reduce((sum, item) => sum + item.quantity, 0)}</span>
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
          ))}
        </section>
      )}
    </div>
  );
}
