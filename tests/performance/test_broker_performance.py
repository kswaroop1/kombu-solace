from __future__ import annotations

import os
import time
import tracemalloc
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


def _payload() -> dict:
    return {"task": "benchmark", "data": "x" * 256}


@pytest.mark.parametrize("confirm_mode", ["sync", "async"])
def test_publish_consume_ack_throughput_smoke(confirm_mode):
    count = _message_count()
    connection = _connection(publish_confirm_mode=confirm_mode)
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"perf-{confirm_mode}-{suffix}"
    exchange = Exchange(f"perf-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)
    queue(channel).declare()
    producer = Producer(channel, exchange=exchange)
    payload = _payload()

    publish_started = time.perf_counter()
    for _ in range(count):
        producer.publish(payload, routing_key=queue_name)
    connection.transport.adapter.flush_publisher(10000)
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
        f"mode={confirm_mode} published={count} publish_rate={publish_rate:.2f}/s "
        f"consume_ack_rate={consume_rate:.2f}/s"
    )

    assert publish_rate > 0
    assert consume_rate > 0


def test_multi_queue_routing_overhead_smoke():
    count = max(1, min(_message_count(), 100))
    queue_count = int(os.environ.get("SOLACE_PERF_QUEUE_COUNT", "3"))
    connection = _connection(publish_confirm_mode="sync")
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    exchange = Exchange(f"perf-topic-{suffix}", type="topic")
    queue_names = [f"perf-fanout-{suffix}-{i}" for i in range(queue_count)]
    for queue_name in queue_names:
        Queue(queue_name, exchange=exchange, routing_key="task.#")(channel).declare()
    producer = Producer(channel, exchange=exchange)

    started = time.perf_counter()
    for _ in range(count):
        producer.publish(_payload(), routing_key="task.created")
    elapsed = time.perf_counter() - started

    delivered = 0
    for queue_name in queue_names:
        for _ in range(count):
            message = channel.basic_get(queue_name)
            assert message is not None
            message.ack()
            delivered += 1
    connection.close()

    print(
        f"multi_queue_messages={count} queues={queue_count} "
        f"solace_publishes={count * queue_count} elapsed={elapsed:.4f}s"
    )
    assert delivered == count * queue_count


def test_bounded_backpressure_memory_smoke():
    count = max(1, min(_message_count(), 200))
    connection = _connection(
        publish_confirm_mode="async",
        publisher_back_pressure_strategy="wait",
        publisher_buffer_capacity=10,
    )
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"perf-memory-{suffix}"
    exchange = Exchange(f"perf-memory-tasks-{suffix}", type="direct")
    Queue(queue_name, exchange=exchange, routing_key=queue_name)(channel).declare()
    producer = Producer(channel, exchange=exchange)

    tracemalloc.start()
    try:
        for _ in range(count):
            producer.publish(_payload(), routing_key=queue_name)
        connection.transport.adapter.flush_publisher(10000)
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        connection.close()

    print(f"bounded_backpressure_messages={count} current_bytes={current} peak_bytes={peak}")
    assert peak > 0


def test_slow_consumer_low_prefetch_memory_smoke():
    count = max(1, min(_message_count(), 100))
    connection = _connection(publish_confirm_mode="sync")
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)
    suffix = uuid.uuid4().hex
    queue_name = f"perf-slow-{suffix}"
    exchange = Exchange(f"perf-slow-tasks-{suffix}", type="direct")
    Queue(queue_name, exchange=exchange, routing_key=queue_name)(channel).declare()
    producer = Producer(channel, exchange=exchange)
    for _ in range(count):
        producer.publish(_payload(), routing_key=queue_name)

    tracemalloc.start()
    try:
        for _ in range(count):
            message = channel.basic_get(queue_name)
            assert message is not None
            time.sleep(0.001)
            message.ack()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        connection.close()

    print(f"slow_consumer_messages={count} current_bytes={current} peak_bytes={peak}")
    assert peak > 0


@pytest.mark.skipif(
    os.environ.get("SOLACE_RUN_SOAK") != "1",
    reason="Solace soak test not enabled",
)
def test_publish_consume_soak():
    count = int(os.environ.get("SOLACE_SOAK_MESSAGE_COUNT", "10000"))
    connection = _connection(publish_confirm_mode="async")
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"soak-{suffix}"
    exchange = Exchange(f"soak-tasks-{suffix}", type="direct")
    Queue(queue_name, exchange=exchange, routing_key=queue_name)(channel).declare()
    producer = Producer(channel, exchange=exchange)

    tracemalloc.start()
    started = time.perf_counter()
    try:
        for i in range(count):
            producer.publish({"i": i, "data": "x" * 256}, routing_key=queue_name)
        connection.transport.adapter.flush_publisher(30000)
        for _ in range(count):
            message = channel.basic_get(queue_name)
            assert message is not None
            message.ack()
        elapsed = time.perf_counter() - started
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        connection.close()

    print(
        f"soak_messages={count} elapsed={elapsed:.2f}s "
        f"current_bytes={current} peak_bytes={peak}"
    )
    assert peak > 0
