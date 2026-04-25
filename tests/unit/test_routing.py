from __future__ import annotations

from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.transport import Transport


def make_connection(adapter):
    return Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )


def test_direct_exchange_uses_kombu_routing_and_internal_queue_topics():
    adapter = InMemorySolaceAdapter()
    connection = make_connection(adapter)
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    queue = Queue("celery", exchange=exchange, routing_key="celery")

    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")

    assert len(adapter.published) == 1
    published_topic = adapter.published[0][0]
    assert published_topic in adapter.subscriptions["celery"]
    assert published_topic.startswith("_kombu/")
    assert "tasks" not in published_topic


def test_topic_exchange_uses_kombu_topic_semantics():
    adapter = InMemorySolaceAdapter()
    connection = make_connection(adapter)
    channel = connection.channel()
    exchange = Exchange("tasks", type="topic")
    Queue("all-tasks", exchange=exchange, routing_key="task.#")(channel).declare()

    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="task.created")

    assert len(adapter.published) == 1


def test_unmatched_route_does_not_publish_to_solace():
    adapter = InMemorySolaceAdapter()
    connection = make_connection(adapter)
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    Queue("celery", exchange=exchange, routing_key="celery")(channel).declare()

    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="other")

    assert adapter.published == []


def test_duplicate_binding_does_not_create_duplicate_internal_subscriptions():
    adapter = InMemorySolaceAdapter()
    connection = make_connection(adapter)
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    queue = Queue("celery", exchange=exchange, routing_key="celery")

    queue(channel).declare()
    queue(channel).declare()

    assert len(adapter.subscriptions["celery"]) == 1
