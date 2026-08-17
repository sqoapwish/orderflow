from celery import Celery

from orderflow.core.config import Settings

settings = Settings()

celery_app = Celery(
    "orderflow",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=["orderflow.workers.tasks"],
)
celery_app.conf.update(
    accept_content=["json"],
    beat_schedule={
        "dispatch-outbox-events": {
            "task": "orderflow.outbox.dispatch",
            "schedule": settings.outbox_dispatch_interval_seconds,
            "options": {"queue": "outbox"},
        }
    },
    broker_transport_options={"confirm_publish": True},
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    task_publish_retry=True,
    task_publish_retry_policy={
        "max_retries": 5,
        "interval_start": 0,
        "interval_step": 0.5,
        "interval_max": 5,
    },
    task_routes={
        "orderflow.events.consume": {"queue": "domain-events"},
        "orderflow.outbox.dispatch": {"queue": "outbox"},
    },
    task_reject_on_worker_lost=True,
    task_serializer="json",
    timezone="UTC",
    worker_prefetch_multiplier=1,
)
