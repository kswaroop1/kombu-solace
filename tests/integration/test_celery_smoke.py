from __future__ import annotations

import os
import uuid

import pytest
from celery import Celery
from celery.contrib.testing.worker import start_worker

import kombu_solace


pytestmark = pytest.mark.integration


def _celery_enabled() -> bool:
    return os.environ.get("SOLACE_RUN_CELERY") == "1"


def _broker_url() -> str:
    host = os.environ.get("SOLACE_HOST", "localhost")
    port = int(os.environ.get("SOLACE_PORT", "55588"))
    user = os.environ.get("SOLACE_USERNAME", "sampleUser")
    password = os.environ.get("SOLACE_PASSWORD", "samplePassword")
    vpn = os.environ.get("SOLACE_VPN", "default")
    return f"solace://{user}:{password}@{host}:{port}/{vpn}"


@pytest.mark.skipif(not _celery_enabled(), reason="Solace Celery smoke not enabled")
def test_celery_solo_worker_executes_task_through_solace_broker():
    kombu_solace.register_transport()
    suffix = uuid.uuid4().hex
    queue_name = f"celery-smoke-{suffix}"
    app = Celery(
        f"kombu_solace_smoke_{suffix}",
        broker=_broker_url(),
        backend="cache+memory://",
    )
    app.conf.update(
        task_default_queue=queue_name,
        task_queues=None,
        task_always_eager=False,
        task_store_eager_result=False,
        result_expires=60,
        broker_transport_options={
            "environment": os.environ.get("SOLACE_ENVIRONMENT", "DEV1"),
            "namespace": os.environ.get("SOLACE_NAMESPACE", "kombu-solace-celery"),
            "application": os.environ.get("SOLACE_APPLICATION", "celery-smoke"),
            "queue_name_prefix": os.environ.get("SOLACE_QUEUE_PREFIX", "it"),
            "topic_prefix": os.environ.get("SOLACE_TOPIC_PREFIX", "it/celery"),
            "publish_confirm_mode": "sync",
            "publish_ack_timeout_ms": 10000,
            "publisher_buffer_capacity": 100,
            "receive_timeout": 1.0,
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
    )

    @app.task(name=f"tasks.add_{suffix}")
    def add(x, y):
        return x + y

    with start_worker(
        app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        without_heartbeat=True,
    ):
        result = add.apply_async(args=(2, 3), queue=queue_name)
        assert result.get(timeout=30) == 5
