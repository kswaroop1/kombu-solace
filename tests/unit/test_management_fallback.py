from __future__ import annotations

import pytest
from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.errors import ManagementUnavailable
from kombu_solace.transport import Transport


class FakeManagement:
    def __init__(self, *, size=None, purge=None, fail=False):
        self.size = size
        self.purge = purge
        self.fail = fail
        self.size_calls = []
        self.purge_calls = []

    def queue_size(self, queue_name):
        self.size_calls.append(queue_name)
        if self.fail:
            raise ManagementUnavailable("SEMP unavailable")
        return self.size

    def purge_queue(self, queue_name):
        self.purge_calls.append(queue_name)
        if self.fail:
            raise ManagementUnavailable("SEMP unavailable")
        return self.purge


def make_channel(adapter, management=None, **transport_options):
    options = {"adapter": adapter, "namespace": "unit", **transport_options}
    if management is not None:
        options["management_adapter"] = management
    connection = Connection(transport=Transport, transport_options=options)
    return connection.channel()


def publish_messages(channel, count):
    exchange = Exchange("tasks", type="direct")
    Queue("celery", exchange=exchange, routing_key="celery")(channel).declare()
    producer = Producer(channel, exchange=exchange)
    for i in range(count):
        producer.publish({"i": i}, routing_key="celery")


def test_size_uses_semp_when_available():
    adapter = InMemorySolaceAdapter()
    management = FakeManagement(size=42)
    channel = make_channel(adapter, management=management)

    assert channel._size("celery") == 42
    assert management.size_calls == ["celery"]


def test_size_falls_back_to_queue_browser_count_when_semp_unavailable():
    adapter = InMemorySolaceAdapter()
    management = FakeManagement(fail=True)
    channel = make_channel(adapter, management=management)
    publish_messages(channel, 3)
    management.size_calls.clear()

    assert channel._size("celery") == 3
    assert management.size_calls == ["celery"]


def test_size_semp_strategy_raises_when_semp_unavailable():
    adapter = InMemorySolaceAdapter()
    management = FakeManagement(fail=True)
    channel = make_channel(adapter, management=management, size_strategy="semp")

    with pytest.raises(ManagementUnavailable):
        channel._size("celery")


def test_purge_uses_semp_when_available():
    adapter = InMemorySolaceAdapter()
    management = FakeManagement(purge=11)
    channel = make_channel(adapter, management=management)

    assert channel._purge("celery") == 11
    assert management.purge_calls == ["celery"]


def test_purge_falls_back_to_receive_and_ack_when_semp_unavailable():
    adapter = InMemorySolaceAdapter()
    management = FakeManagement(fail=True)
    channel = make_channel(adapter, management=management)
    publish_messages(channel, 4)

    assert channel._purge("celery") == 4
    assert channel._size("celery") == 0


def test_purge_can_be_bounded_by_max_messages():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter, purge_strategy="receiver", purge_max_messages=2)
    publish_messages(channel, 4)

    assert channel._purge("celery") == 2
    assert channel._size("celery") == 2
