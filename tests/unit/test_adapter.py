from __future__ import annotations

from collections import deque
from threading import Condition
from unittest.mock import Mock

import pytest
from solace.messaging.config.solace_properties import service_properties
from solace.messaging.config.solace_properties import transport_layer_properties
from solace.messaging.publisher.persistent_message_publisher import (
    MessagePublishReceiptListener,
)

from kombu_solace.adapter import InMemorySolaceAdapter
from kombu_solace.adapter import _PublishReceiptListener, build_service_properties
from kombu_solace.adapter import PubSubPlusSolaceAdapter
from kombu_solace.errors import PublishFailed
from kombu_solace.errors import QueueUnavailable
from kombu_solace.errors import SettlementFailed


class FakeAuth:
    calls = []

    @classmethod
    def of(cls, username, password):
        cls.calls.append((username, password))
        return ("auth", username, password)


class FakeMessagingService:
    builder_instance = None

    @classmethod
    def builder(cls):
        cls.builder_instance = FakeServiceBuilder()
        return cls.builder_instance


class FakeServiceBuilder:
    def __init__(self):
        self.properties = None
        self.auth = None
        self.service = FakeService()

    def from_properties(self, properties):
        self.properties = properties
        return self

    def with_authentication_strategy(self, auth):
        self.auth = auth
        return self

    def build(self):
        return self.service


class FakeService:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.is_connected = True
        self.publisher_builder = FakePublisherBuilder()
        self.receiver_builder = FakeReceiverBuilder()
        self.browser_builder = FakeBrowserBuilder()

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True
        self.is_connected = False

    def create_persistent_message_publisher_builder(self):
        return self.publisher_builder

    def create_persistent_message_receiver_builder(self):
        return self.receiver_builder

    def create_message_queue_browser_builder(self):
        return self.browser_builder


class FakePublisherBuilder:
    def __init__(self):
        self.strategy = None
        self.capacity = None
        self.publisher = FakePublisher()

    def on_back_pressure_wait(self, capacity):
        self.strategy = "wait"
        self.capacity = capacity
        return self

    def on_back_pressure_reject(self, capacity):
        self.strategy = "reject"
        self.capacity = capacity
        return self

    def on_back_pressure_elastic(self):
        self.strategy = "elastic"
        return self

    def build(self):
        return self.publisher


class FakePublisher:
    def __init__(self):
        self.started = False
        self.terminated = False
        self.is_terminated = False
        self.listener = None
        self.published = []
        self.sync_published = []
        self.fail_sync = False
        self.fail_async = False

    def start(self):
        self.started = True

    def terminate(self):
        self.terminated = True
        self.is_terminated = True

    def set_message_publish_receipt_listener(self, listener):
        self.listener = listener

    def publish_await_acknowledgement(self, payload, destination, time_out):
        if self.fail_sync:
            raise RuntimeError("sync failed")
        self.sync_published.append((payload, destination, time_out))

    def publish(self, payload, destination, user_context):
        if self.fail_async:
            raise RuntimeError("async failed")
        self.published.append((payload, destination, user_context))


class FakeReceiverBuilder:
    def __init__(self):
        self.client_ack = False
        self.missing_strategy = None
        self.outcomes = None
        self.receiver = FakeReceiver()
        self.built_queues = []

    def with_message_client_acknowledgement(self):
        self.client_ack = True
        return self

    def with_missing_resources_creation_strategy(self, strategy):
        self.missing_strategy = strategy
        return self

    def with_required_message_outcome_support(self, *outcomes):
        self.outcomes = outcomes
        return self

    def build(self, queue):
        self.built_queues.append(queue)
        return self.receiver


class FakeReceiver:
    def __init__(self):
        self.started = False
        self.terminated = False
        self.is_terminated = False
        self.subscriptions = []
        self.messages = deque()
        self.acked = []
        self.settled = []
        self.fail_ack = False
        self.fail_settle = False

    def start(self):
        self.started = True

    def terminate(self):
        self.terminated = True
        self.is_terminated = True

    def add_subscription(self, subscription):
        self.subscriptions.append(subscription)

    def receive_message(self, timeout_ms):
        try:
            return self.messages.popleft()
        except IndexError:
            return None

    def ack(self, message):
        if self.fail_ack:
            raise RuntimeError("ack failed")
        self.acked.append(message)

    def settle(self, message, outcome):
        if self.fail_settle:
            raise RuntimeError("settle failed")
        self.settled.append((message, outcome))


class FakeInboundMessage:
    def __init__(self, payload):
        self.payload = payload

    def get_payload_as_string(self):
        return self.payload


class FakeBrowserBuilder:
    def __init__(self):
        self.browser = FakeBrowser()
        self.built_queues = []

    def build(self, queue):
        self.built_queues.append(queue)
        return self.browser


class FakeBrowser:
    def __init__(self):
        self.started = False
        self.terminated = False
        self.messages = deque()

    def start(self):
        self.started = True

    def terminate(self):
        self.terminated = True

    def receive_message(self, timeout_ms):
        try:
            return self.messages.popleft()
        except IndexError:
            return None


class FakeImmediateCondition:
    def __init__(self, pending):
        self.pending = pending

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def wait(self):
        self.pending[0] = 0


class FakePublishReceipt:
    def __init__(self, *, is_persisted=True, exception=None):
        self.is_persisted = is_persisted
        self.exception = exception


def test_build_service_properties_uses_solace_property_keys():
    props = build_service_properties(
        {
            "hostname": "broker.example.com",
            "port": 55443,
            "transport_scheme": "tcps",
            "vpn_name": "prod-vpn",
        }
    )

    assert props[transport_layer_properties.HOST] == "tcps://broker.example.com:55443"
    assert props[service_properties.VPN_NAME] == "prod-vpn"


def test_build_service_properties_preserves_explicit_host_uri():
    props = build_service_properties(
        {
            "hostname": "tcp://broker.example.com:55555",
            "port": 1234,
            "vpn_name": "default",
        }
    )

    assert props[transport_layer_properties.HOST] == "tcp://broker.example.com:55555"


def test_build_service_properties_defaults_host_and_vpn():
    props = build_service_properties({})

    assert props[transport_layer_properties.HOST] == "tcp://localhost:55555"
    assert props[service_properties.VPN_NAME] == "default"


def test_publish_receipt_listener_matches_solace_required_type():
    listener = _PublishReceiptListener(failures=[])

    assert isinstance(listener, MessagePublishReceiptListener)


def test_publish_receipt_success_decrements_pending_count():
    failures = deque()
    condition = Condition()
    pending = [1]
    listener = _PublishReceiptListener(
        failures,
        condition=condition,
        pending_counter=pending,
    )

    listener.on_publish_receipt(FakePublishReceipt(is_persisted=True))

    assert pending == [0]
    assert not failures


def test_publish_receipt_failure_records_failure_and_decrements_pending_count():
    failures = deque()
    condition = Condition()
    pending = [1]
    listener = _PublishReceiptListener(
        failures,
        condition=condition,
        pending_counter=pending,
    )

    listener.on_publish_receipt(
        FakePublishReceipt(is_persisted=False, exception=RuntimeError("rejected"))
    )

    assert pending == [0]
    assert isinstance(failures[0], RuntimeError)


def test_publish_receipt_without_condition_and_without_exception_records_default_failure():
    failures = deque()
    listener = _PublishReceiptListener(failures)

    listener.on_publish_receipt(FakePublishReceipt(is_persisted=False))

    assert isinstance(failures[0], PublishFailed)


def test_publish_receipt_with_no_pending_counter_only_records_failure():
    failures = deque()
    listener = _PublishReceiptListener(failures, condition=Condition())

    listener.on_publish_receipt(FakePublishReceipt(is_persisted=False))

    assert isinstance(failures[0], PublishFailed)


def test_publish_receipt_with_zero_pending_counter_does_not_decrement():
    pending = [0]
    listener = _PublishReceiptListener(deque(), condition=Condition(), pending_counter=pending)

    listener.on_publish_receipt(FakePublishReceipt(is_persisted=True))

    assert pending == [0]


def test_pending_publish_receipt_failure_surfaces_on_flush():
    adapter = PubSubPlusSolaceAdapter()
    adapter._publish_failures.append(RuntimeError("broker rejected publish"))

    try:
        adapter.flush_publisher(timeout_ms=100)
    except PublishFailed as exc:
        assert "broker rejected publish" in str(exc)
    else:
        raise AssertionError("expected PublishFailed")


def test_flush_publisher_times_out_with_pending_receipts():
    adapter = PubSubPlusSolaceAdapter()
    adapter._pending_publishes[0] = 1

    with pytest.raises(PublishFailed, match="timed out waiting for 1"):
        adapter.flush_publisher(timeout_ms=1)


def test_wait_for_publish_receipts_without_timeout_returns_when_notified():
    adapter = PubSubPlusSolaceAdapter()
    adapter._pending_publishes[0] = 0

    adapter.flush_publisher(timeout_ms=None)


def test_wait_for_publish_receipts_without_timeout_waits_until_pending_clears():
    adapter = PubSubPlusSolaceAdapter()
    adapter._pending_publishes[0] = 1
    adapter._publish_condition = FakeImmediateCondition(adapter._pending_publishes)

    adapter.flush_publisher(timeout_ms=None)

    assert adapter._pending_publishes == [0]


def test_connect_builds_service_and_publisher(monkeypatch):
    FakeAuth.calls = []
    import solace.messaging.config.authentication_strategy as auth_module
    import solace.messaging.messaging_service as service_module

    monkeypatch.setattr(auth_module, "BasicUserNamePassword", FakeAuth)
    monkeypatch.setattr(service_module, "MessagingService", FakeMessagingService)
    adapter = PubSubPlusSolaceAdapter()

    adapter.connect(
        {
            "hostname": "broker.example.com",
            "port": 55555,
            "userid": "user",
            "password": "pass",
            "vpn_name": "vpn",
            "publisher_back_pressure_strategy": "reject",
            "publisher_buffer_capacity": 12,
            "browser_timeout_ms": 7,
            "purge_receive_timeout_ms": 8,
            "purge_max_messages": 9,
        }
    )

    assert adapter.service.connected is True
    assert adapter.publisher.started is True
    assert FakeAuth.calls == [("user", "pass")]
    assert adapter.service.publisher_builder.strategy == "reject"
    assert adapter.service.publisher_builder.capacity == 12
    assert adapter.browser_timeout_ms == 7
    assert adapter.purge_receive_timeout_ms == 8
    assert adapter.purge_max_messages == 9


def test_connect_without_authentication(monkeypatch):
    import solace.messaging.messaging_service as service_module

    monkeypatch.setattr(service_module, "MessagingService", FakeMessagingService)
    adapter = PubSubPlusSolaceAdapter()

    adapter.connect({})

    assert FakeMessagingService.builder_instance.auth is None


def test_close_terminates_receivers_publisher_and_service():
    adapter = PubSubPlusSolaceAdapter()
    receiver = FakeReceiver()
    adapter.receivers["queue"] = receiver
    adapter.subscriptions["queue"].add("topic")
    adapter.publisher = FakePublisher()
    adapter.service = FakeService()

    adapter.close()

    assert receiver.terminated is True
    assert adapter.receivers == {}
    assert adapter.subscriptions == {}
    assert adapter.publisher.terminated is True
    assert adapter.service.disconnected is True


def test_close_skips_terminated_or_disconnected_resources():
    adapter = PubSubPlusSolaceAdapter()
    publisher = FakePublisher()
    publisher.is_terminated = True
    service = FakeService()
    service.is_connected = False
    adapter.publisher = publisher
    adapter.service = service

    adapter.close()

    assert publisher.terminated is False
    assert service.disconnected is False


def test_ensure_queue_creates_receiver_and_reuses_existing_receiver():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()

    adapter.ensure_queue("queue")
    receiver = adapter.receivers["queue"]
    adapter.ensure_queue("queue")

    assert adapter.receivers["queue"] is receiver
    assert receiver.started is True


def test_queue_exists_returns_false_when_receiver_creation_fails(monkeypatch):
    adapter = PubSubPlusSolaceAdapter()
    monkeypatch.setattr(adapter, "ensure_queue", Mock(side_effect=RuntimeError("boom")))

    assert adapter.queue_exists("queue") is False


def test_queue_exists_returns_true_when_receiver_exists():
    adapter = PubSubPlusSolaceAdapter()
    adapter.receivers["queue"] = FakeReceiver()

    assert adapter.queue_exists("queue") is True


def test_ensure_queue_subscription_adds_once():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()

    adapter.ensure_queue_subscription("queue", "a/b")
    adapter.ensure_queue_subscription("queue", "a/b")

    receiver = adapter.receivers["queue"]
    assert len(receiver.subscriptions) == 1
    assert adapter.subscriptions["queue"] == {"a/b"}


def test_publish_sync_success_and_failure():
    adapter = PubSubPlusSolaceAdapter()
    adapter.publisher = FakePublisher()
    adapter.publish_ack_timeout_ms = 123

    adapter.publish("topic", "payload", confirm_policy="sync")
    adapter.publisher.fail_sync = True

    assert adapter.publisher.sync_published[0][0] == "payload"
    with pytest.raises(PublishFailed, match="sync failed"):
        adapter.publish("topic", "payload", confirm_policy="sync")


def test_publish_async_success_and_failure():
    adapter = PubSubPlusSolaceAdapter()
    adapter.publisher = FakePublisher()

    adapter.publish("topic", "payload", confirm_policy="async")
    adapter.publisher.fail_async = True

    assert adapter._pending_publishes == [1]
    assert adapter.publisher.published[0][0] == "payload"
    with pytest.raises(RuntimeError, match="async failed"):
        adapter.publish("topic", "payload", confirm_policy="async")
    assert adapter._pending_publishes == [1]


def test_publish_async_failure_does_not_decrement_zero_pending_counter():
    adapter = PubSubPlusSolaceAdapter()
    adapter.publisher = FakePublisher()
    adapter.publisher.fail_async = True
    adapter._pending_publishes[0] = -1

    with pytest.raises(RuntimeError, match="async failed"):
        adapter.publish("topic", "payload", confirm_policy="async")

    assert adapter._pending_publishes == [0]


def test_receive_returns_payload_and_empty():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()
    adapter.ensure_queue("queue")
    receiver = adapter.receivers["queue"]
    message = FakeInboundMessage("payload")
    receiver.messages.append(message)

    inbound = adapter.receive("queue", timeout_ms=1)

    assert inbound.payload == "payload"
    assert inbound.delivery_ref == (receiver, message)
    with pytest.raises(Exception):
        adapter.receive("queue", timeout_ms=1)


def test_ack_and_settlement_success_and_failure():
    adapter = PubSubPlusSolaceAdapter()
    receiver = FakeReceiver()
    message = object()

    adapter.ack((receiver, message))
    adapter.settle_failed((receiver, message))
    adapter.settle_rejected((receiver, message))

    assert receiver.acked == [message]
    assert len(receiver.settled) == 2
    receiver.fail_ack = True
    with pytest.raises(SettlementFailed, match="ack failed"):
        adapter.ack((receiver, message))
    receiver.fail_settle = True
    with pytest.raises(SettlementFailed, match="settle failed"):
        adapter.settle_failed((receiver, message))


def test_close_receiver_handles_missing_existing_and_terminated():
    adapter = PubSubPlusSolaceAdapter()
    adapter.close_receiver("missing")
    receiver = FakeReceiver()
    adapter.receivers["queue"] = receiver
    adapter.subscriptions["queue"].add("topic")

    adapter.close_receiver("queue")

    assert receiver.terminated is True
    assert "queue" not in adapter.subscriptions
    receiver = FakeReceiver()
    receiver.is_terminated = True
    adapter.receivers["done"] = receiver
    adapter.close_receiver("done")
    assert receiver.terminated is False


def test_queue_size_by_browsing_counts_and_terminates_browser():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()
    browser = adapter.service.browser_builder.browser
    browser.messages.extend([object(), object()])

    assert adapter.queue_size_by_browsing("queue", timeout_ms=1) == 2
    assert browser.started is True
    assert browser.terminated is True


def test_purge_by_receiving_acks_until_empty_or_limit():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()
    adapter.ensure_queue("queue")
    receiver = adapter.receivers["queue"]
    receiver.messages.extend([object(), object(), object()])

    assert adapter.purge_by_receiving("queue", timeout_ms=1, max_messages=2) == 2
    assert len(receiver.acked) == 2
    assert adapter.purge_by_receiving("queue", timeout_ms=1) == 1


def test_build_publisher_supports_elastic_and_reject_and_rejects_unknown_strategy():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()
    adapter.publisher_back_pressure_strategy = "elastic"
    assert adapter._build_publisher().started is True
    assert adapter.service.publisher_builder.strategy == "elastic"

    adapter.service = FakeService()
    adapter.publisher_back_pressure_strategy = "bad"
    with pytest.raises(ValueError, match="unknown publisher back-pressure"):
        adapter._build_publisher()


def test_build_receiver_supports_non_durable_without_create_or_nacks():
    adapter = PubSubPlusSolaceAdapter()
    adapter.service = FakeService()
    adapter.create_missing_queues = False
    adapter.enable_nacks = False

    receiver = adapter._build_receiver("queue", durable=False)

    assert receiver.started is True
    assert adapter.service.receiver_builder.client_ack is True
    assert adapter.service.receiver_builder.missing_strategy is not None
    assert adapter.service.receiver_builder.outcomes is None


def test_in_memory_adapter_queue_unavailable_empty_topic_and_empty_queue_paths():
    adapter = InMemorySolaceAdapter()
    adapter.connect({"create_missing_queues": False})

    with pytest.raises(QueueUnavailable):
        adapter.ensure_queue("missing")

    adapter.create_missing_queues = True
    adapter.ensure_queue_subscription("queue", "a")
    adapter.ensure_queue_subscription("queue", "b")
    adapter.messages_by_topic["b"].append("payload")

    assert adapter.receive("queue").payload == "payload"
    with pytest.raises(Exception):
        adapter.receive("queue")
