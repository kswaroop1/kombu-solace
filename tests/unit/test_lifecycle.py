from __future__ import annotations

from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.transport import Transport


def test_receiver_close_forgets_subscription_cache_so_redeclare_resubscribes():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    exchange = Exchange("tasks", type="direct")
    queue = Queue("celery", exchange=exchange, routing_key="celery")

    queue(channel).declare()
    first_topic = next(iter(adapter.subscriptions["celery"]))
    channel.close()

    channel = connection.channel()
    queue(channel).declare()

    assert adapter.subscriptions["celery"] == {first_topic}


def test_anonymous_exchange_publishes_directly_to_routing_key_queue():
    adapter = InMemorySolaceAdapter()
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    channel = connection.channel()
    Queue("celery")(channel).declare()

    Producer(channel).publish({"ok": True}, routing_key="celery")
    message = channel.basic_get("celery")

    assert message.payload == {"ok": True}
    assert len(adapter.published) == 1
