from __future__ import annotations

from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.transport import Transport


def make_channel(adapter):
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    return connection.channel()


def publish_one(channel):
    exchange = Exchange("tasks", type="direct")
    Queue("celery", exchange=exchange, routing_key="celery")(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")


def test_ack_calls_solace_ack_before_qos_state_is_removed():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter)
    publish_one(channel)

    message = channel.basic_get("celery")
    delivery_ref = channel._delivery_refs[message.delivery_tag]

    channel.basic_ack(message.delivery_tag)

    assert adapter.acked == [delivery_ref]
    assert message.delivery_tag not in channel.qos._delivered


def test_reject_requeue_maps_to_failed_outcome():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter)
    publish_one(channel)

    message = channel.basic_get("celery")
    delivery_ref = channel._delivery_refs[message.delivery_tag]

    channel.basic_reject(message.delivery_tag, requeue=True)

    assert adapter.failed == [delivery_ref]
    assert adapter.rejected == []


def test_reject_without_requeue_maps_to_rejected_outcome():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter)
    publish_one(channel)

    message = channel.basic_get("celery")
    delivery_ref = channel._delivery_refs[message.delivery_tag]

    channel.basic_reject(message.delivery_tag, requeue=False)

    assert adapter.rejected == [delivery_ref]
    assert adapter.failed == []


def test_channel_close_does_not_restore_unacked_by_republishing():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter)
    publish_one(channel)
    message = channel.basic_get("celery")

    assert channel.do_restore is False
    channel.close()

    assert len(adapter.published) == 1
    assert adapter.acked == []
    assert message.delivery_tag in channel.qos._delivered

