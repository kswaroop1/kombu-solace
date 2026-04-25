from __future__ import annotations

import os
import time
import uuid

import pytest
from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.transport import Transport


pytestmark = [
    pytest.mark.performance,
    pytest.mark.skipif(
        os.environ.get("SOLACE_RUN_PERFORMANCE") != "1",
        reason="Solace performance tests not enabled",
    ),
]


def _message_count() -> int:
    return int(os.environ.get("SOLACE_PERF_MESSAGE_COUNT", "1000"))


def _connection(**transport_options) -> Connection:
    options = {
        "environment": os.environ.get("SOLACE_ENVIRONMENT", "PERF"),
        "namespace": os.environ.get("SOLACE_NAMESPACE", "kombu-solace-perf"),
        "publish_confirm_mode": os.environ.get("SOLACE_PUBLISH_CONFIRM_MODE", "sync"),
        "publish_ack_timeout_ms": 10000,
        "publisher_buffer_capacity": int(
            os.environ.get("SOLACE_PUBLISHER_BUFFER_CAPACITY", "1000")
        ),
        "receive_timeout": 1.0,
    }
    options.update(transport_options)
    return Connection(
        transport=Transport,
        hostname=os.environ.get("SOLACE_HOST", "localhost"),
        port=int(os.environ.get("SOLACE_PORT", "55588")),
        userid=os.environ.get("SOLACE_USERNAME", "sampleUser"),
        password=os.environ.get("SOLACE_PASSWORD", "samplePassword"),
        virtual_host=os.environ.get("SOLACE_VPN", "default"),
        transport_options=options,
    )


def test_publish_consume_ack_throughput_smoke():
    count = _message_count()
    connection = _connection()
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"perf-{suffix}"
    exchange = Exchange(f"perf-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)
    queue(channel).declare()
    producer = Producer(channel, exchange=exchange)
    payload = {"task": "benchmark", "data": "x" * 256}

    publish_started = time.perf_counter()
    for _ in range(count):
        producer.publish(payload, routing_key=queue_name)
    publish_elapsed = time.perf_counter() - publish_started

    consume_started = time.perf_counter()
    for _ in range(count):
        message = channel.basic_get(queue_name)
        assert message is not None
        message.ack()
    consume_elapsed = time.perf_counter() - consume_started
    connection.close()

    publish_rate = count / publish_elapsed
    consume_rate = count / consume_elapsed
    print(
        f"published={count} publish_rate={publish_rate:.2f}/s "
        f"consume_ack_rate={consume_rate:.2f}/s"
    )

    assert publish_rate > 0
    assert consume_rate > 0
