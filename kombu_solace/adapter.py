"""Adapter boundary for Solace messaging APIs.

The concrete Solace implementation will live behind this module. Unit tests use
the in-memory adapter below so Kombu behavior is tested without a broker.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from queue import Empty
from typing import Protocol

from .errors import PublishFailed, QueueUnavailable, SettlementFailed


@dataclass(frozen=True)
class SolaceInbound:
    """Inbound payload plus the broker-specific delivery reference."""

    payload: dict | str | bytes
    delivery_ref: object


@dataclass(frozen=True)
class PublishResult:
    """Result returned by adapter publish calls."""

    accepted: bool = True
    error: Exception | None = None


class SolaceMessagingAdapter(Protocol):
    """Protocol implemented by real and fake Solace adapters."""

    def connect(self, settings: dict) -> None: ...

    def close(self) -> None: ...

    def ensure_queue(self, queue_name: str, *, durable: bool = True) -> None: ...

    def queue_exists(self, queue_name: str) -> bool: ...

    def ensure_queue_subscription(self, queue_name: str, topic: str) -> None: ...

    def publish(
        self,
        topic: str,
        payload: str,
        headers: dict | None = None,
        properties: dict | None = None,
        confirm_policy: str = "async",
    ) -> PublishResult: ...

    def receive(self, queue_name: str, timeout_ms: int | None = None) -> SolaceInbound: ...

    def ack(self, delivery_ref: object) -> None: ...

    def settle_failed(self, delivery_ref: object) -> None: ...

    def settle_rejected(self, delivery_ref: object) -> None: ...

    def close_receiver(self, queue_name: str) -> None: ...

    def flush_publisher(self, timeout_ms: int | None = None) -> None: ...

    def queue_size_by_browsing(self, queue_name: str, timeout_ms: int) -> int: ...

    def purge_by_receiving(
        self,
        queue_name: str,
        *,
        timeout_ms: int,
        max_messages: int | None = None,
    ) -> int: ...


class SolaceManagementAdapter(Protocol):
    """Optional management adapter, typically backed by SEMP."""

    def queue_size(self, queue_name: str) -> int: ...

    def purge_queue(self, queue_name: str) -> int: ...


def build_service_properties(settings: dict) -> dict:
    """Build Solace service properties from Kombu connection settings."""

    from solace.messaging.config.solace_properties import service_properties
    from solace.messaging.config.solace_properties import transport_layer_properties

    hostname = settings.get("hostname") or "localhost"
    port = settings.get("port") or 55555
    scheme = settings.get("transport_scheme") or "tcp"
    if "://" in hostname:
        host = hostname
    else:
        host = f"{scheme}://{hostname}:{port}"

    return {
        transport_layer_properties.HOST: host,
        service_properties.VPN_NAME: settings.get("vpn_name") or settings.get("virtual_host") or "default",
    }


try:
    from solace.messaging.publisher.persistent_message_publisher import (
        MessagePublishReceiptListener as _SolaceReceiptListenerBase,
    )
except Exception:  # pragma: no cover - used only when dependency import fails
    _SolaceReceiptListenerBase = object


class _PublishReceiptListener(_SolaceReceiptListenerBase):
    def __init__(self, failures: deque[Exception]) -> None:
        self.failures = failures

    def on_publish_receipt(self, publish_receipt):
        if not publish_receipt.is_persisted:
            exc = publish_receipt.exception
            if exc is None:
                exc = PublishFailed("Solace publish was not persisted")
            self.failures.append(exc)


class PubSubPlusSolaceAdapter:
    """Real adapter over `solace-pubsubplus`.

    The adapter is intentionally thin; Kombu transport semantics stay in
    `transport.py`, while Solace builder and receiver/publisher calls stay here.
    """

    def __init__(self) -> None:
        self.service = None
        self.publisher = None
        self.receivers: dict[str, object] = {}
        self.subscriptions: dict[str, set[str]] = defaultdict(set)
        self.create_missing_queues = True
        self.enable_nacks = True
        self.publish_confirm_mode = "async"
        self.publish_ack_timeout_ms = 30000
        self.publisher_back_pressure_strategy = "wait"
        self.publisher_buffer_capacity = 1000
        self.browser_timeout_ms = 100
        self.purge_receive_timeout_ms = 100
        self.purge_max_messages: int | None = None
        self._publish_failures: deque[Exception] = deque()

    def connect(self, settings: dict) -> None:
        from solace.messaging.config.authentication_strategy import BasicUserNamePassword
        from solace.messaging.messaging_service import MessagingService

        self.create_missing_queues = settings.get("create_missing_queues", True)
        self.enable_nacks = settings.get("enable_nacks", True)
        self.publish_confirm_mode = settings.get("publish_confirm_mode", "async")
        self.publish_ack_timeout_ms = settings.get("publish_ack_timeout_ms", 30000)
        self.publisher_back_pressure_strategy = settings.get(
            "publisher_back_pressure_strategy", "wait"
        )
        self.publisher_buffer_capacity = settings.get("publisher_buffer_capacity", 1000)
        self.browser_timeout_ms = settings.get("browser_timeout_ms", 100)
        self.purge_receive_timeout_ms = settings.get("purge_receive_timeout_ms", 100)
        self.purge_max_messages = settings.get("purge_max_messages")

        builder = MessagingService.builder().from_properties(
            build_service_properties(settings)
        )
        if settings.get("userid") is not None or settings.get("password") is not None:
            builder = builder.with_authentication_strategy(
                BasicUserNamePassword.of(
                    settings.get("userid") or "",
                    settings.get("password") or "",
                )
            )
        self.service = builder.build()
        self.service.connect()
        self.publisher = self._build_publisher()

    def close(self) -> None:
        for receiver in list(self.receivers.values()):
            receiver.terminate()
        self.receivers.clear()
        self.subscriptions.clear()
        if self.publisher is not None and not self.publisher.is_terminated:
            self.publisher.terminate()
        if self.service is not None and self.service.is_connected:
            self.service.disconnect()

    def ensure_queue(self, queue_name: str, *, durable: bool = True) -> None:
        if queue_name in self.receivers:
            return
        self.receivers[queue_name] = self._build_receiver(queue_name, durable=durable)

    def queue_exists(self, queue_name: str) -> bool:
        try:
            self.ensure_queue(queue_name)
        except Exception:
            return False
        return True

    def ensure_queue_subscription(self, queue_name: str, topic: str) -> None:
        from solace.messaging.resources.topic_subscription import TopicSubscription

        self.ensure_queue(queue_name)
        if topic in self.subscriptions[queue_name]:
            return
        receiver = self.receivers[queue_name]
        receiver.add_subscription(TopicSubscription.of(topic))
        self.subscriptions[queue_name].add(topic)

    def publish(
        self,
        topic: str,
        payload: str,
        headers: dict | None = None,
        properties: dict | None = None,
        confirm_policy: str = "async",
    ) -> PublishResult:
        from solace.messaging.resources.topic import Topic

        self._raise_publish_failure()
        destination = Topic.of(topic)
        if confirm_policy == "sync":
            try:
                self.publisher.publish_await_acknowledgement(
                    payload, destination, time_out=self.publish_ack_timeout_ms
                )
            except Exception as exc:
                raise PublishFailed(str(exc)) from exc
            return PublishResult()
        self.publisher.publish(payload, destination, user_context=topic)
        self._raise_publish_failure()
        return PublishResult()

    def receive(self, queue_name: str, timeout_ms: int | None = None) -> SolaceInbound:
        self.ensure_queue(queue_name)
        receiver = self.receivers[queue_name]
        message = receiver.receive_message(timeout_ms)
        if message is None:
            raise Empty()
        payload = message.get_payload_as_string()
        return SolaceInbound(payload=payload, delivery_ref=(receiver, message))

    def ack(self, delivery_ref: object) -> None:
        receiver, message = delivery_ref
        try:
            receiver.ack(message)
        except Exception as exc:
            raise SettlementFailed(str(exc)) from exc

    def settle_failed(self, delivery_ref: object) -> None:
        self._settle(delivery_ref, "FAILED")

    def settle_rejected(self, delivery_ref: object) -> None:
        self._settle(delivery_ref, "REJECTED")

    def close_receiver(self, queue_name: str) -> None:
        receiver = self.receivers.pop(queue_name, None)
        self.subscriptions.pop(queue_name, None)
        if receiver is not None and not receiver.is_terminated:
            receiver.terminate()

    def flush_publisher(self, timeout_ms: int | None = None) -> None:
        self._raise_publish_failure()

    def queue_size_by_browsing(self, queue_name: str, timeout_ms: int) -> int:
        from solace.messaging.resources.queue import Queue

        browser = self.service.create_message_queue_browser_builder().build(
            Queue.durable_non_exclusive_queue(queue_name)
        )
        count = 0
        try:
            browser.start()
            while browser.receive_message(timeout_ms) is not None:
                count += 1
        finally:
            browser.terminate()
        return count

    def purge_by_receiving(
        self,
        queue_name: str,
        *,
        timeout_ms: int,
        max_messages: int | None = None,
    ) -> int:
        self.ensure_queue(queue_name)
        receiver = self.receivers[queue_name]
        count = 0
        while max_messages is None or count < max_messages:
            message = receiver.receive_message(timeout_ms)
            if message is None:
                break
            receiver.ack(message)
            count += 1
        return count

    def _build_publisher(self):
        builder = self.service.create_persistent_message_publisher_builder()
        if self.publisher_back_pressure_strategy == "wait":
            builder = builder.on_back_pressure_wait(self.publisher_buffer_capacity)
        elif self.publisher_back_pressure_strategy == "reject":
            builder = builder.on_back_pressure_reject(self.publisher_buffer_capacity)
        elif self.publisher_back_pressure_strategy == "elastic":
            builder = builder.on_back_pressure_elastic()
        else:
            raise ValueError(
                f"unknown publisher back-pressure strategy: {self.publisher_back_pressure_strategy}"
            )
        publisher = builder.build()
        publisher.start()
        publisher.set_message_publish_receipt_listener(
            _PublishReceiptListener(self._publish_failures)
        )
        return publisher

    def _build_receiver(self, queue_name: str, *, durable: bool):
        from solace.messaging.config.message_acknowledgement_configuration import Outcome
        from solace.messaging.config.missing_resources_creation_configuration import (
            MissingResourcesCreationStrategy,
        )
        from solace.messaging.resources.queue import Queue

        queue = (
            Queue.durable_non_exclusive_queue(queue_name)
            if durable
            else Queue.non_durable_exclusive_queue(queue_name)
        )
        builder = self.service.create_persistent_message_receiver_builder()
        builder = builder.with_message_client_acknowledgement()
        if self.create_missing_queues:
            builder = builder.with_missing_resources_creation_strategy(
                MissingResourcesCreationStrategy.CREATE_ON_START
            )
        else:
            builder = builder.with_missing_resources_creation_strategy(
                MissingResourcesCreationStrategy.DO_NOT_CREATE
            )
        if self.enable_nacks:
            builder = builder.with_required_message_outcome_support(
                Outcome.FAILED, Outcome.REJECTED
            )
        receiver = builder.build(queue)
        receiver.start()
        return receiver

    def _settle(self, delivery_ref: object, outcome_name: str) -> None:
        from solace.messaging.config.message_acknowledgement_configuration import Outcome

        receiver, message = delivery_ref
        outcome = getattr(Outcome, outcome_name)
        try:
            receiver.settle(message, outcome)
        except Exception as exc:
            raise SettlementFailed(str(exc)) from exc

    def _raise_publish_failure(self) -> None:
        if self._publish_failures:
            exc = self._publish_failures.popleft()
            raise PublishFailed(str(exc)) from exc


class InMemorySolaceAdapter:
    """Deterministic fake adapter for unit tests."""

    def __init__(self) -> None:
        self.connected = False
        self.closed = False
        self.queues: set[str] = set()
        self.subscriptions: dict[str, set[str]] = defaultdict(set)
        self.messages_by_topic: dict[str, deque[str]] = defaultdict(deque)
        self.published: list[tuple[str, str, dict | None, dict | None, str]] = []
        self.acked: list[object] = []
        self.failed: list[object] = []
        self.rejected: list[object] = []
        self.closed_receivers: list[str] = []
        self.flushed = False
        self.create_missing_queues = True
        self._delivery_id = 0

    def connect(self, settings: dict) -> None:
        self.connected = True
        self.create_missing_queues = settings.get("create_missing_queues", True)

    def close(self) -> None:
        self.closed = True
        self.subscriptions.clear()

    def ensure_queue(self, queue_name: str, *, durable: bool = True) -> None:
        if not self.create_missing_queues and queue_name not in self.queues:
            raise QueueUnavailable(queue_name)
        self.queues.add(queue_name)

    def queue_exists(self, queue_name: str) -> bool:
        return queue_name in self.queues

    def ensure_queue_subscription(self, queue_name: str, topic: str) -> None:
        self.ensure_queue(queue_name)
        self.subscriptions[queue_name].add(topic)

    def publish(
        self,
        topic: str,
        payload: str,
        headers: dict | None = None,
        properties: dict | None = None,
        confirm_policy: str = "async",
    ) -> PublishResult:
        self.published.append((topic, payload, headers, properties, confirm_policy))
        self.messages_by_topic[topic].append(payload)
        return PublishResult()

    def receive(self, queue_name: str, timeout_ms: int | None = None) -> SolaceInbound:
        for topic in sorted(self.subscriptions[queue_name]):
            try:
                payload = self.messages_by_topic[topic].popleft()
            except IndexError:
                continue
            self._delivery_id += 1
            return SolaceInbound(payload=payload, delivery_ref=(queue_name, self._delivery_id))
        raise Empty()

    def ack(self, delivery_ref: object) -> None:
        self.acked.append(delivery_ref)

    def settle_failed(self, delivery_ref: object) -> None:
        self.failed.append(delivery_ref)

    def settle_rejected(self, delivery_ref: object) -> None:
        self.rejected.append(delivery_ref)

    def close_receiver(self, queue_name: str) -> None:
        self.closed_receivers.append(queue_name)
        self.subscriptions.pop(queue_name, None)

    def flush_publisher(self, timeout_ms: int | None = None) -> None:
        self.flushed = True

    def queue_size_by_browsing(self, queue_name: str, timeout_ms: int) -> int:
        return sum(len(self.messages_by_topic[topic]) for topic in self.subscriptions[queue_name])

    def purge_by_receiving(
        self,
        queue_name: str,
        *,
        timeout_ms: int,
        max_messages: int | None = None,
    ) -> int:
        count = 0
        for topic in sorted(self.subscriptions[queue_name]):
            while max_messages is None or count < max_messages:
                try:
                    self.messages_by_topic[topic].popleft()
                except IndexError:
                    break
                count += 1
            if max_messages is not None and count >= max_messages:
                break
        return count
