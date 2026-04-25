from __future__ import annotations

import os
import time
import uuid

import pytest
from celery import Celery
from celery.exceptions import Reject, TimeoutError as CeleryTimeoutError
from celery.contrib.testing.worker import start_worker
from kombu import Connection

import kombu_solace
from kombu_solace.transport import Transport


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


def _broker_transport_options() -> dict:
    return {
        "environment": os.environ.get("SOLACE_ENVIRONMENT", "DEV1"),
        "namespace": os.environ.get("SOLACE_NAMESPACE", "kombu-solace-celery"),
        "application": os.environ.get("SOLACE_APPLICATION", "celery-smoke"),
        "queue_name_prefix": os.environ.get("SOLACE_QUEUE_PREFIX", "it"),
        "topic_prefix": os.environ.get("SOLACE_TOPIC_PREFIX", "it/celery"),
        "publish_confirm_mode": "sync",
        "publish_ack_timeout_ms": 10000,
        "publisher_buffer_capacity": 100,
        "receive_timeout": 1.0,
    }


def _kombu_connection() -> Connection:
    return Connection(
        transport=Transport,
        hostname=os.environ.get("SOLACE_HOST", "localhost"),
        port=int(os.environ.get("SOLACE_PORT", "55588")),
        userid=os.environ.get("SOLACE_USERNAME", "sampleUser"),
        password=os.environ.get("SOLACE_PASSWORD", "samplePassword"),
        virtual_host=os.environ.get("SOLACE_VPN", "default"),
        transport_options=_broker_transport_options(),
    )


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
        broker_transport_options=_broker_transport_options(),
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
        broker_pool_limit=0,
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
        result = add.apply_async(args=(4, 6), queue=queue_name)
        assert result.get(timeout=30) == 10


@pytest.mark.skipif(not _celery_enabled(), reason="Solace Celery smoke not enabled")
def test_celery_retry_publishes_and_executes_retry_through_solace_broker():
    kombu_solace.register_transport()
    suffix = uuid.uuid4().hex
    queue_name = f"celery-retry-{suffix}"
    app = Celery(
        f"kombu_solace_retry_{suffix}",
        broker=_broker_url(),
        backend="cache+memory://",
    )
    attempts = []
    app.conf.update(
        task_default_queue=queue_name,
        task_queues=None,
        task_always_eager=False,
        result_expires=60,
        broker_transport_options=_broker_transport_options(),
        worker_prefetch_multiplier=2,
        task_acks_late=False,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
        broker_pool_limit=0,
    )

    @app.task(bind=True, name=f"tasks.retry_once_{suffix}", max_retries=1)
    def retry_once(self):
        attempts.append(self.request.retries)
        if self.request.retries == 0:
            raise self.retry(countdown=0)
        return self.request.retries

    with start_worker(
        app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        without_heartbeat=True,
    ):
        result = retry_once.apply_async(queue=queue_name)
        try:
            assert result.get(timeout=30) == 1
        except CeleryTimeoutError:
            pytest.fail(f"retry task timed out; observed attempts={attempts}")


@pytest.mark.skipif(not _celery_enabled(), reason="Solace Celery smoke not enabled")
def test_celery_reject_without_requeue_discards_task_message():
    kombu_solace.register_transport()
    suffix = uuid.uuid4().hex
    queue_name = f"celery-reject-{suffix}"
    app = Celery(
        f"kombu_solace_reject_{suffix}",
        broker=_broker_url(),
        backend="cache+memory://",
    )
    attempts = []
    app.conf.update(
        task_default_queue=queue_name,
        task_queues=None,
        task_always_eager=False,
        result_expires=60,
        broker_transport_options=_broker_transport_options(),
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        worker_enable_remote_control=False,
        worker_send_task_events=False,
        task_send_sent_event=False,
        broker_pool_limit=0,
    )

    @app.task(bind=True, name=f"tasks.reject_discard_{suffix}")
    def reject_discard(self):
        attempts.append(self.request.id)
        raise Reject("discard", requeue=False)

    with start_worker(
        app,
        pool="solo",
        concurrency=1,
        perform_ping_check=False,
        without_heartbeat=True,
    ):
        reject_discard.apply_async(queue=queue_name)
        deadline = time.monotonic() + 30
        while not attempts and time.monotonic() < deadline:
            time.sleep(0.1)
        assert len(attempts) == 1

        connection = _kombu_connection()
        channel = connection.channel()
        try:
            assert channel.basic_get(queue_name) is None
        finally:
            connection.close()
