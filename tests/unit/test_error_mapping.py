from __future__ import annotations

import pytest
from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.errors import SolaceChannelError, SolaceConnectionError
from kombu_solace.transport import Transport


class FailingDeclareAdapter(InMemorySolaceAdapter):
    def ensure_queue(self, queue_name: str, *, durable: bool = True) -> None:
        raise RuntimeError("declare failed")


class FailingConnectAdapter(InMemorySolaceAdapter):
    def connect(self, settings: dict) -> None:
        raise RuntimeError("connect failed")


class FailingPublishAdapter(InMemorySolaceAdapter):
    def publish(self, *args, **kwargs):
        raise RuntimeError("publish failed")


class FailingReceiveAdapter(InMemorySolaceAdapter):
    def receive(self, queue_name: str, timeout_ms: int | None = None):
        raise RuntimeError("receive failed")


def make_channel(adapter):
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": adapter, "namespace": "unit"},
    )
    return connection.channel()


def test_connect_errors_are_connection_errors():
    connection = Connection(
        transport=Transport,
        transport_options={"adapter": FailingConnectAdapter()},
    )

    with pytest.raises(SolaceConnectionError, match="connect failed"):
        connection.channel()


def test_queue_declare_errors_are_channel_errors():
    channel = make_channel(FailingDeclareAdapter())

    with pytest.raises(SolaceChannelError, match="queue declaration failed"):
        Queue("celery")(channel).declare()


def test_publish_errors_are_connection_errors():
    adapter = FailingPublishAdapter()
    channel = make_channel(adapter)
    exchange = Exchange("tasks", type="direct")
    Queue("celery", exchange=exchange, routing_key="celery")(channel).declare()

    with pytest.raises(SolaceConnectionError, match="publish failed"):
        Producer(channel, exchange=exchange).publish({"ok": True}, routing_key="celery")


def test_receive_errors_are_connection_errors():
    channel = make_channel(FailingReceiveAdapter())

    with pytest.raises(SolaceConnectionError, match="receive failed"):
        channel.basic_get("celery")


def test_transport_exposes_mapped_errors_to_kombu_retry_layer():
    transport = Connection(transport=Transport).transport

    assert SolaceConnectionError in transport.connection_errors
    assert SolaceChannelError in transport.channel_errors
