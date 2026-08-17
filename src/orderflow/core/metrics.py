from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from threading import Lock
from time import perf_counter
from typing import Protocol

import structlog
from fastapi import Request, Response

_LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


@dataclass(frozen=True, slots=True)
class OutboxMetricsSnapshot:
    pending: int = 0
    published: int = 0
    dead_letter: int = 0
    delivery_attempts: int = 0
    oldest_pending_age_seconds: float = 0.0


class OutboxMetricsProvider(Protocol):
    async def snapshot(self) -> OutboxMetricsSnapshot: ...


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._in_progress = 0
        self._request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self._duration_counts: dict[tuple[str, str], int] = defaultdict(int)
        self._duration_sums: dict[tuple[str, str], float] = defaultdict(float)
        self._duration_buckets: dict[tuple[str, str, float], int] = defaultdict(int)

    def request_started(self) -> None:
        with self._lock:
            self._in_progress += 1

    def request_finished(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (method, route)
        with self._lock:
            self._in_progress -= 1
            self._request_counts[method, route, status_code] += 1
            self._duration_counts[key] += 1
            self._duration_sums[key] += duration_seconds
            for bucket in _LATENCY_BUCKETS:
                if duration_seconds <= bucket:
                    self._duration_buckets[method, route, bucket] += 1

    def render(
        self,
        *,
        version: str,
        outbox: OutboxMetricsSnapshot,
        outbox_scrape_success: bool,
    ) -> str:
        with self._lock:
            in_progress = self._in_progress
            request_counts = dict(self._request_counts)
            duration_counts = dict(self._duration_counts)
            duration_sums = dict(self._duration_sums)
            duration_buckets = dict(self._duration_buckets)

        lines = [
            "# HELP orderflow_build_info OrderFlow build information.",
            "# TYPE orderflow_build_info gauge",
            f'orderflow_build_info{{version="{_escape_label(version)}"}} 1',
            "# HELP orderflow_http_requests_in_progress Requests currently being processed.",
            "# TYPE orderflow_http_requests_in_progress gauge",
            f"orderflow_http_requests_in_progress {in_progress}",
            "# HELP orderflow_http_requests_total Completed HTTP requests.",
            "# TYPE orderflow_http_requests_total counter",
        ]
        for (method, route, status_code), count in sorted(request_counts.items()):
            lines.append(
                "orderflow_http_requests_total"
                f'{{method="{_escape_label(method)}",route="{_escape_label(route)}",'
                f'status="{status_code}"}} {count}'
            )

        lines.extend(
            [
                "# HELP orderflow_http_request_duration_seconds HTTP request latency.",
                "# TYPE orderflow_http_request_duration_seconds histogram",
            ]
        )
        for method, route in sorted(duration_counts):
            labels = f'method="{_escape_label(method)}",route="{_escape_label(route)}"'
            for bucket in _LATENCY_BUCKETS:
                value = duration_buckets.get((method, route, bucket), 0)
                lines.append(
                    "orderflow_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{bucket:g}"}} {value}'
                )
            count = duration_counts[method, route]
            lines.append(
                f'orderflow_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {count}'
            )
            lines.append(
                f"orderflow_http_request_duration_seconds_sum{{{labels}}} "
                f"{duration_sums[method, route]:.9f}"
            )
            lines.append(f"orderflow_http_request_duration_seconds_count{{{labels}}} {count}")

        lines.extend(
            [
                "# HELP orderflow_outbox_metrics_scrape_success "
                "Whether PostgreSQL Outbox metrics were read.",
                "# TYPE orderflow_outbox_metrics_scrape_success gauge",
                f"orderflow_outbox_metrics_scrape_success {int(outbox_scrape_success)}",
                "# HELP orderflow_outbox_events Current Outbox rows by status.",
                "# TYPE orderflow_outbox_events gauge",
                f'orderflow_outbox_events{{status="pending"}} {outbox.pending}',
                f'orderflow_outbox_events{{status="published"}} {outbox.published}',
                f'orderflow_outbox_events{{status="dead_letter"}} {outbox.dead_letter}',
                "# HELP orderflow_outbox_delivery_attempts_total "
                "Persisted failed delivery attempts.",
                "# TYPE orderflow_outbox_delivery_attempts_total counter",
                f"orderflow_outbox_delivery_attempts_total {outbox.delivery_attempts}",
                "# HELP orderflow_outbox_oldest_pending_age_seconds "
                "Age of the oldest pending event.",
                "# TYPE orderflow_outbox_oldest_pending_age_seconds gauge",
                "orderflow_outbox_oldest_pending_age_seconds "
                f"{outbox.oldest_pending_age_seconds:.3f}",
            ]
        )
        return "\n".join(lines) + "\n"


def build_metrics_middleware(
    registry: MetricsRegistry,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    async def metrics_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started_at = perf_counter()
        status_code = 500
        registry.request_started()
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_seconds = perf_counter() - started_at
            route = _route_template(request)
            registry.request_finished(
                method=request.method,
                route=route,
                status_code=status_code,
                duration_seconds=duration_seconds,
            )
            if route != "/metrics":
                structlog.get_logger().info(
                    "http_request_completed",
                    method=request.method,
                    route=route,
                    status_code=status_code,
                    duration_ms=round(duration_seconds * 1000, 3),
                )

    return metrics_middleware


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _route_template(request: Request) -> str:
    fastapi_scope = request.scope.get("fastapi")
    if isinstance(fastapi_scope, dict):
        effective_route = fastapi_scope.get("effective_route_context")
        effective_path = getattr(effective_route, "path", None)
        if isinstance(effective_path, str):
            return effective_path
    route_path = getattr(request.scope.get("route"), "path", None)
    return route_path if isinstance(route_path, str) else "unmatched"
