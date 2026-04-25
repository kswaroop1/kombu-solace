from __future__ import annotations

from queue import Empty

import pytest
from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.transport import Transport


def test_consumer_drain_events_delivers_message_and_tracks_ack():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    queue = Queue("celery", exchange=exchange, routing_key="celery")
    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")

    seen = []
    queue(channel).consume(callback=lambda message: seen.append(message))
    connection.drain_events(timeout=0)

    assert seen[0].payload == {"ok": True}
    assert seen[0].delivery_tag in channel.qos._delivered


def test_drain_events_empty_raises_timeout_or_empty():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    Queue("celery")(channel).declare()

    with pytest.raises((Empty, TimeoutError, OSError)):
        connection.drain_events(timeout=0)


def test_basic_get_no_ack_immediately_acks_solace_delivery():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    Queue("celery", exchange=exchange, routing_key="celery")(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")

    message = channel.basic_get("celery", no_ack=True)

    assert message.payload == {"ok": True}
    assert adapter.acked == [("celery", 1)]
    assert message.delivery_tag not in channel.qos._delivered


def test_consume_no_ack_immediately_acks_before_callback_delivery():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    queue = Queue("celery", exchange=exchange, routing_key="celery")
    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")

    seen = []
    queue(channel).consume(no_ack=True, callback=lambda message: seen.append(message))
    connection.drain_events(timeout=0)

    assert seen[0].payload == {"ok": True}
    assert adapter.acked == [("celery", 1)]
    assert seen[0].delivery_tag not in channel.qos._delivered
