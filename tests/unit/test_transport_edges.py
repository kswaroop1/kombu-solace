from __future__ import annotations

from queue import Empty
from unittest.mock import Mock, patch

import pytest
from kombu import Connection

from kombu_solace.adapter import InMemorySolaceAdapter, SolaceInbound
from kombu_solace.errors import ManagementUnavailable, QueueUnavailable, SettlementFailed
from kombu_solace.transport import Channel, Transport


class FailingAckAdapter(InMemorySolaceAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.fail_ack = False
        self.fail_failed = False
        self.fail_rejected = False

    def ack(self, delivery_ref):
        if self.fail_ack:
            raise RuntimeError("ack failed")
        super().ack(delivery_ref)

    def settle_failed(self, delivery_ref):
        if self.fail_failed:
            raise RuntimeError("failed settlement failed")
        super().settle_failed(delivery_ref)

    def settle_rejected(self, delivery_ref):
        if self.fail_rejected:
            raise RuntimeError("rejected settlement failed")
        super().settle_rejected(delivery_ref)


class NoTagAdapter(InMemorySolaceAdapter):
    def receive(self, queue_name: str, timeout_ms: int | None = None):
        return SolaceInbound(payload={"body": "payload", "properties": {}}, delivery_ref="ref")


class EmptyAdapter(InMemorySolaceAdapter):
    def receive(self, queue_name: str, timeout_ms: int | None = None):
        raise Empty()


class DeclaredQueueUnavailableAdapter(InMemorySolaceAdapter):
    def ensure_queue(self, queue_name: str, *, durable: bool = True) -> None:
        raise QueueUnavailable(queue_name)


class FailingManagement:
    def queue_size(self, queue_name):
        raise ManagementUnavailable("no SEMP")

    def purge_queue(self, queue_name):
        raise ManagementUnavailable("no SEMP")


def make_channel(adapter=None, **transport_options):
    options = {"adapter": adapter or InMemorySolaceAdapter(), "namespace": "unit", **transport_options}
    connection = Connection(transport=Transport, transport_options=options)
    return connection.channel()


def test_new_queue_preserves_queue_unavailable_errors():
    channel = make_channel(DeclaredQueueUnavailableAdapter())

    with pytest.raises(QueueUnavailable):
        channel._new_queue("celery")


def test_has_queue_delegates_to_physical_queue_name():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(
        adapter,
        environment="DEV1",
        application="orders",
        queue_name_prefix="corp",
    )
    adapter.queues.add("corp.orders.DEV1.celery")

    assert channel._has_queue("celery") is True


def test_get_empty_and_missing_delivery_tag_paths():
    with pytest.raises(Empty):
        make_channel(EmptyAdapter())._get("celery")

    channel = make_channel(NoTagAdapter())

    message = channel._get("celery")

    assert message["body"] == "payload"
    assert channel._delivery_refs == {}


def test_disabled_size_and_purge_return_zero_and_delete_closes_receiver():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter, size_strategy="disabled", purge_strategy="disabled")
    channel._known_queues.add("celery")

    assert channel._size("celery") == 0
    assert channel._purge("celery") == 0

    channel._delete("celery")

    assert adapter.closed_receivers == ["celery"]
    assert "celery" not in channel._known_queues


def test_semp_only_size_and_purge_raise_management_unavailable():
    channel = make_channel(
        management_adapter=FailingManagement(),
        size_strategy="semp",
        purge_strategy="semp",
    )

    with pytest.raises(ManagementUnavailable):
        channel._size("celery")
    with pytest.raises(ManagementUnavailable):
        channel._purge("celery")


def test_basic_ack_raw_ack_and_reject_missing_tags_delegate_without_error():
    channel = make_channel()

    channel.basic_ack("missing")
    channel._ack_raw_delivery("missing")
    channel.basic_reject("missing", requeue=False)


def test_basic_reject_missing_tag_requeue_uses_kombu_restore_path():
    channel = make_channel()

    with pytest.raises(KeyError):
        channel.basic_reject("missing", requeue=True)


def test_ack_failures_restore_delivery_refs():
    adapter = FailingAckAdapter()
    channel = make_channel(adapter)
    channel._delivery_refs["tag"] = "ref"
    adapter.fail_ack = True

    with pytest.raises(SettlementFailed, match="ack failed"):
        channel.basic_ack("tag")

    assert channel._delivery_refs["tag"] == "ref"

    with pytest.raises(SettlementFailed, match="ack failed"):
        channel._ack_raw_delivery("tag")

    assert channel._delivery_refs["tag"] == "ref"


def test_reject_failures_restore_delivery_refs_for_both_outcomes():
    adapter = FailingAckAdapter()
    channel = make_channel(adapter)
    channel._delivery_refs["failed"] = "ref"
    adapter.fail_failed = True

    with pytest.raises(SettlementFailed, match="failed settlement failed"):
        channel.basic_reject("failed", requeue=True)

    assert channel._delivery_refs["failed"] == "ref"
    channel._delivery_refs["rejected"] = "ref"
    adapter.fail_rejected = True

    with pytest.raises(SettlementFailed, match="rejected settlement failed"):
        channel.basic_reject("rejected", requeue=False)

    assert channel._delivery_refs["rejected"] == "ref"


def test_get_and_deliver_no_ack_without_delivery_tag_still_delivers():
    channel = make_channel(NoTagAdapter())
    channel._no_ack_queues.add("celery")
    seen = []

    channel._get_and_deliver("celery", lambda message, queue: seen.append((message, queue)))

    assert seen == [({"body": "payload", "properties": {}}, "celery")]


def test_basic_recover_is_not_supported_and_timeout_accepts_none():
    channel = make_channel()
    channel.receive_timeout = None

    assert channel._timeout_ms(None) is None
    assert channel._timeout_ms(-1) == 0
    with pytest.raises(NotImplementedError, match="does not republish"):
        channel.basic_recover()


def test_close_on_already_closed_channel_skips_receiver_close():
    adapter = InMemorySolaceAdapter()
    channel = make_channel(adapter)
    channel._known_queues.add("celery")
    channel.closed = True

    channel.close()

    assert adapter.closed_receivers == []


def test_transport_factories_defaults_and_connection_settings():
    adapter = InMemorySolaceAdapter()
    management = object()
    connection = Connection(
        transport=Transport,
        transport_options={
            "adapter_factory": lambda: adapter,
            "management_adapter_factory": lambda: management,
            "namespace": "unit",
        },
    )
    transport = connection.transport

    assert transport.adapter is adapter
    assert transport.management is management
    assert transport.default_connection_params == {"port": 55555, "hostname": "localhost"}
    assert transport._connection_settings()["port"] == 55555


def test_transport_can_build_default_adapters_and_semp_management_adapter():
    connection = Connection(
        "solace://user:pass@broker.example.com/default",
        transport=Transport,
        transport_options={"semp_url": "https://broker.example.com:943"},
    )
    transport = connection.transport

    assert transport.adapter.__class__.__name__ == "PubSubPlusSolaceAdapter"
    assert transport.management.base_url == "https://broker.example.com:943"
    assert transport.management.vpn_name == "default"


def test_establish_connection_wraps_existing_connection_errors():
    error = RuntimeError("connect failed")
    adapter = Mock()
    adapter.connect.side_effect = error
    connection = Connection(transport=Transport, transport_options={"adapter": adapter})

    with pytest.raises(Exception, match="connect failed"):
        connection.channel()


def test_close_connection_flushes_and_closes_adapter_even_when_super_is_patched():
    adapter = InMemorySolaceAdapter()
    connection = Connection(transport=Transport, transport_options={"adapter": adapter})
    transport = connection.transport
    channel = Mock(spec=Channel)
    transport.channels.append(channel)

    with patch("kombu_solace.transport.virtual.Transport.close_connection") as close:
        transport.close_connection(object())

    channel.close.assert_called_once_with()
    assert adapter.flushed is True
    assert adapter.closed is True
    close.assert_called_once()
