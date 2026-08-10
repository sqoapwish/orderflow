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
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    timezone="UTC",
    worker_prefetch_multiplier=1,
)
