from orderflow.workers.celery_app import celery_app
from orderflow.workers.tasks import ping


def test_celery_uses_rabbitmq_and_json_serialization() -> None:
    assert celery_app.conf.broker_url.startswith("amqp://")
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_publish_retry is True
    assert celery_app.conf.broker_transport_options["confirm_publish"] is True
    assert (
        celery_app.conf.beat_schedule["dispatch-outbox-events"]["task"]
        == "orderflow.outbox.dispatch"
    )


def test_ping_task_can_execute_locally() -> None:
    assert ping.run() == {"status": "pong"}
