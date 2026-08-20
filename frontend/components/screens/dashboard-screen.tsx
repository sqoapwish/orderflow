"use client";

import { type CSSProperties, useCallback, useEffect, useMemo, useState } from "react";

import { apiRequest } from "@/lib/api";
import { chartPoints, formatDateTime, formatMoney, formatShortDate } from "@/lib/format";
import type {
  LowStockPage,
  OrderPage,
  SalesAnalytics,
  TopProducts,
  User,
} from "@/lib/types";

import type { Screen } from "../app-shell";
import { EmptyState, ErrorState, Icon, LoadingBlock, ProductMark, StatusBadge } from "../ui";

interface DashboardData {
  sales: SalesAnalytics;
  products: TopProducts;
  stock: LowStockPage;
  orders: OrderPage;
}

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

export function DashboardScreen({
  user,
  onNavigate,
}: {
  user: User | null;
  onNavigate: (screen: Screen) => void;
}) {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadDashboard = useCallback(async (selectedDays: number) => {
    if (!user || user.role === "customer") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - selectedDays + 1);
    const period = new URLSearchParams({ date_from: isoDate(start), date_to: isoDate(end) });
    try {
      const [sales, products, stock, orders] = await Promise.all([
        apiRequest<SalesAnalytics>(`/analytics/sales?${period}`),
        apiRequest<TopProducts>(`/analytics/products/top?${period}&limit=5`),
        apiRequest<LowStockPage>("/analytics/inventory/low-stock?threshold=10&page_size=5"),
        apiRequest<OrderPage>("/orders?page_size=100"),
      ]);
      setData({ sales, products, stock, orders });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить аналитику");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadDashboard(30), 0);
    return () => window.clearTimeout(timer);
  }, [loadDashboard]);

  const primaryCurrency = data?.sales.currencies[0];
  const daily = useMemo(
    () => data?.sales.daily.filter((row) => row.currency === primaryCurrency?.currency) ?? [],
    [data, primaryCurrency?.currency],
  );
  const successRate = primaryCurrency
    ? Math.round((primaryCurrency.paid_orders / Math.max(primaryCurrency.paid_orders + primaryCurrency.failed_payments, 1)) * 1000) / 10
    : 0;

  if (!user || user.role === "customer") {
    return <div className="page-shell"><EmptyState icon="analytics" title="Аналитика доступна менеджеру" text="Для просмотра бизнес-показателей нужна роль manager или admin." /></div>;
  }

  return (
    <div className="page-shell dashboard-shell">
      <section className="page-heading split-heading">
        <div>
          <span className="eyebrow">Операционная аналитика</span>
          <h1>Добрый день, {user.email.split("@")[0]}</h1>
          <p>Вот что происходит с заказами и складом прямо сейчас.</p>
        </div>
        <label className="date-filter">
          <Icon name="calendar" size={18} />
          <select
            aria-label="Период аналитики"
            value={days}
            onChange={(event) => {
              const value = Number(event.target.value);
              setDays(value);
              void loadDashboard(value);
            }}
          >
            <option value="7">Последние 7 дней</option>
            <option value="30">Последние 30 дней</option>
            <option value="90">Последние 90 дней</option>
          </select>
        </label>
      </section>
      {error ? <ErrorState message={error} retry={() => void loadDashboard(days)} /> : null}
      {loading ? (
        <LoadingBlock label="Собираем бизнес-показатели" />
      ) : !data ? null : (
        <>
          <section className="dashboard-top">
            <article className="revenue-card card">
              <div className="kpi-row">
                <div><span>Чистая выручка</span><strong>{formatMoney(primaryCurrency?.net_revenue_minor ?? 0, primaryCurrency?.currency)}</strong></div>
                <div><span>Оплачено</span><strong>{formatMoney(primaryCurrency?.gross_revenue_minor ?? 0, primaryCurrency?.currency)}</strong></div>
                <div><span>Возвращено</span><strong>{formatMoney(primaryCurrency?.refunded_amount_minor ?? 0, primaryCurrency?.currency)}</strong></div>
              </div>
              <div className="chart-title"><strong>Выручка по дням</strong><span>{primaryCurrency?.currency ?? "RUB"}</span></div>
              {daily.length ? (
                <div className="line-chart">
                  <svg role="img" aria-label="График чистой выручки" viewBox="0 0 800 230" preserveAspectRatio="none">
                    <line x1="0" y1="40" x2="800" y2="40" /><line x1="0" y1="115" x2="800" y2="115" /><line x1="0" y1="190" x2="800" y2="190" />
                    <polyline points={chartPoints(daily.map((row) => row.net_revenue_minor), 800, 190)} />
                  </svg>
                  <div className="chart-labels">
                    <span>{formatShortDate(daily[0].day)}</span>
                    <span>{formatShortDate(daily[Math.floor(daily.length / 2)].day)}</span>
                    <span>{formatShortDate(daily[daily.length - 1].day)}</span>
                  </div>
                </div>
              ) : <EmptyState title="Пока нет продаж" text="График появится после первого успешного платежа." />}
            </article>
            <div className="dashboard-side">
              <article className="status-card card">
                <div className="card-title"><div><span className="eyebrow">Заказы</span><h2>Текущие статусы</h2></div><button className="text-button" onClick={() => onNavigate("orders")}>Все заказы <Icon name="chevron" size={15} /></button></div>
                <div className="status-summary">
                  {(["pending_payment", "paid", "payment_failed", "refunded"] as const).map((status) => (
                    <div key={status}><StatusBadge status={status} /><strong>{data.orders.items.filter((order) => order.status === status).length}</strong></div>
                  ))}
                </div>
              </article>
              <article className="payment-health card">
                <div><span className="eyebrow">Успешность оплат</span><strong>{successRate}%</strong><p>{primaryCurrency?.failed_payments ?? 0} неуспешных попыток за период</p></div>
                <div className="progress-ring" style={{ "--progress": `${successRate * 3.6}deg` } as CSSProperties}><span>{successRate}%</span></div>
              </article>
            </div>
          </section>

          <section className="dashboard-bottom">
            <article className="card data-card">
              <div className="card-title"><div><span className="eyebrow">Продажи</span><h2>Популярные товары</h2></div></div>
              {data.products.items.length === 0 ? <EmptyState title="Нет данных" text="Оплаченные товары появятся здесь." /> : data.products.items.map((product) => (
                <div className="rank-row" key={product.product_id}>
                  <ProductMark name={product.product_name} />
                  <div><strong>{product.product_name}</strong><span>{product.product_sku}</span></div>
                  <span>{product.paid_quantity} шт.</span>
                  <strong>{formatMoney(product.gross_revenue_minor, product.currency)}</strong>
                </div>
              ))}
            </article>
            <article className="card data-card">
              <div className="card-title"><div><span className="eyebrow">Склад</span><h2>Заканчиваются</h2></div><button className="text-button" onClick={() => onNavigate("warehouse")}>Все остатки <Icon name="chevron" size={15} /></button></div>
              {data.stock.items.length === 0 ? <EmptyState title="Всё в порядке" text="Товаров с низким остатком нет." /> : data.stock.items.map((item) => (
                <div className="stock-row" key={`${item.warehouse_id}:${item.product_id}`}>
                  <span className="warning-dot" />
                  <div><strong>{item.product_name}</strong><span>{item.warehouse_name}</span></div>
                  <strong>{item.available} шт.</strong>
                </div>
              ))}
            </article>
            <article className="card data-card">
              <div className="card-title"><div><span className="eyebrow">Активность</span><h2>Последние заказы</h2></div></div>
              {data.orders.items.length === 0 ? <EmptyState title="Нет заказов" text="Новые операции появятся здесь." /> : data.orders.items.slice(0, 5).map((order) => (
                <div className="activity-row" key={order.id}>
                  <span className={`activity-icon activity-${order.status}`}><Icon name={order.status === "paid" ? "check" : "orders"} size={16} /></span>
                  <div><strong>{order.order_number}</strong><span>{formatDateTime(order.created_at)}</span></div>
                  <strong>{formatMoney(order.total_minor, order.currency)}</strong>
                </div>
              ))}
            </article>
          </section>
        </>
      )}
    </div>
  );
}
