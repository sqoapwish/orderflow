"use client";

import { useCallback, useEffect, useState } from "react";

import { apiRequest } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent, AuditPage, User } from "@/lib/types";

import { EmptyState, ErrorState, Icon, LoadingBlock } from "../ui";

const ACTION_LABELS: Record<string, string> = {
  "order.created": "Заказ создан",
  "order.cancelled": "Заказ отменён",
  "payment.succeeded": "Платёж проведён",
  "payment.failed": "Ошибка платежа",
  "payment.refunded": "Возврат оформлен",
};

export function AuditScreen({ user }: { user: User | null }) {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!user || user.role !== "admin") {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const response = await apiRequest<AuditPage>("/audit/events?page_size=100");
      setEvents(response.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось получить аудит");
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (!user || user.role !== "admin") {
    return <div className="page-shell"><EmptyState icon="audit" title="Аудит доступен администратору" text="История защищена отдельной проверкой роли admin." /></div>;
  }

  return (
    <div className="page-shell">
      <section className="page-heading"><div><span className="eyebrow">Неизменяемая история</span><h1>Аудит действий</h1><p>События нельзя изменить или удалить даже в обход прикладного кода.</p></div></section>
      {error ? <ErrorState message={error} retry={() => void load()} /> : null}
      {loading ? <LoadingBlock label="Загружаем историю" /> : events.length === 0 ? (
        <EmptyState icon="audit" title="Событий пока нет" text="История заполнится после доставки доменных событий." />
      ) : (
        <section className="audit-timeline card">
          {events.map((event) => (
            <article className="audit-row" key={event.id}>
              <span className="audit-icon"><Icon name={event.action.includes("failed") ? "warning" : event.action.includes("refund") ? "logout" : "check"} size={17} /></span>
              <div><strong>{ACTION_LABELS[event.action] ?? event.action}</strong><p>{event.resource_type} · {event.resource_id.slice(0, 8)}</p></div>
              <code>{event.correlation_id?.slice(0, 12) ?? "system"}</code>
              <time dateTime={event.occurred_at}>{formatDateTime(event.occurred_at)}</time>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
