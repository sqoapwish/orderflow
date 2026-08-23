"use client";

import type { ReactNode } from "react";

import { orderStatusLabel } from "@/lib/format";
import type { OrderStatus } from "@/lib/types";

export type IconName =
  | "analytics"
  | "audit"
  | "bag"
  | "box"
  | "calendar"
  | "cart"
  | "check"
  | "chevron"
  | "logout"
  | "orders"
  | "search"
  | "warehouse"
  | "warning"
  | "x";

const paths: Record<IconName, ReactNode> = {
  analytics: <path d="M4 19V9m5 10V5m5 14v-7m5 7V3" />,
  audit: <path d="M7 3h8l4 4v14H7V3Zm8 0v5h4M10 13h6m-6 4h6" />,
  bag: <path d="M6 8h12l1 13H5L6 8Zm3 0a3 3 0 0 1 6 0" />,
  box: <path d="m4 7 8-4 8 4-8 4-8-4Zm0 0v10l8 4 8-4V7m-8 4v10" />,
  calendar: <path d="M5 5h14v15H5V5Zm3-2v4m8-4v4M5 10h14" />,
  cart: <path d="M3 4h2l2 11h10l3-8H6m2 12h.01M17 19h.01" />,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  logout: <path d="M10 4H5v16h5m4-4 4-4-4-4m4 4H9" />,
  orders: <path d="M6 3h12v18H6V3Zm3 5h6m-6 4h6m-6 4h4" />,
  search: <path d="m20 20-4-4m2-5a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z" />,
  warehouse: <path d="m3 10 9-6 9 6v10H3V10Zm4 3h3v3H7v-3Zm7 0h3v3h-3v-3Z" />,
  warning: <path d="M12 4 3 20h18L12 4Zm0 6v4m0 3h.01" />,
  x: <path d="m6 6 12 12M18 6 6 18" />,
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
      stroke="currentColor"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="1.8"
    >
      {paths[name]}
    </svg>
  );
}

export function Logo() {
  return (
    <div className="brand" aria-label="OrderFlow">
      <span className="brand-mark" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <span>OrderFlow</span>
    </div>
  );
}

export function LoadingBlock({ label = "Загружаем данные" }: { label?: string }) {
  return (
    <div className="state-block" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({
  icon = "box",
  title,
  text,
  action,
}: {
  icon?: IconName;
  title: string;
  text: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-icon">
        <Icon name={icon} size={24} />
      </span>
      <h3>{title}</h3>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function ErrorState({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div className="error-state" role="alert">
      <Icon name="warning" />
      <div>
        <strong>Не удалось загрузить данные</strong>
        <p>{message}</p>
      </div>
      {retry ? (
        <button className="button button-secondary" type="button" onClick={retry}>
          Повторить
        </button>
      ) : null}
    </div>
  );
}

export function StatusBadge({ status }: { status: OrderStatus }) {
  return <span className={`status status-${status}`}>{orderStatusLabel(status)}</span>;
}

export function ProductMark({ name, imageUrl }: { name: string; imageUrl?: string | null }) {
  // Product images are supplied by the API at runtime, so their hosts cannot be
  // enumerated in Next.js image configuration ahead of time.
  // eslint-disable-next-line @next/next/no-img-element
  if (imageUrl) return <img className="product-image" src={imageUrl} alt="" />;
  return (
    <span className="product-mark" aria-hidden="true">
      {name.trim().slice(0, 1).toUpperCase()}
    </span>
  );
}
