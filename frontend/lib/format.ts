import type { OrderStatus, PaymentStatus, UserRole } from "./types";

const ORDER_LABELS: Record<OrderStatus, string> = {
  pending_payment: "Ожидает оплаты",
  paid: "Оплачен",
  payment_failed: "Ошибка оплаты",
  cancelled: "Отменён",
  refunded: "Возвращён",
};

const PAYMENT_LABELS: Record<PaymentStatus, string> = {
  pending: "Ожидает",
  succeeded: "Успешно",
  failed: "Ошибка",
  cancelled: "Отменён",
  refunded: "Возвращён",
};

const ROLE_LABELS: Record<UserRole, string> = {
  customer: "Покупатель",
  manager: "Менеджер",
  admin: "Администратор",
};

export function formatMoney(amountMinor: number, currency = "RUB"): string {
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amountMinor / 100);
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function formatShortDate(value: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
  }).format(new Date(`${value}T00:00:00Z`));
}

export function orderStatusLabel(status: OrderStatus): string {
  return ORDER_LABELS[status];
}

export function paymentStatusLabel(status: PaymentStatus): string {
  return PAYMENT_LABELS[status];
}

export function roleLabel(role: UserRole): string {
  return ROLE_LABELS[role];
}

export function initials(email: string): string {
  return email.slice(0, 2).toUpperCase();
}

export function chartPoints(values: number[], width: number, height: number): string {
  if (values.length === 0) return "";
  if (values.length === 1) return `0,${height / 2} ${width},${height / 2}`;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}
