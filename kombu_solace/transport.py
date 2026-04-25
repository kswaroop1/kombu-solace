"""Kombu virtual transport backed by Solace persistent messaging."""

from __future__ import annotations

from queue import Empty

from kombu.exceptions import ChannelError
from kombu.transport import virtual

from .adapter import PubSubPlusSolaceAdapter
from .config import SolaceTransportOptions
from .errors import ManagementUnavailable, QueueUnavailable, SettlementFailed
from .management import SempV2ManagementAdapter
from .naming import queue_ingress_topic
from .serialization import deserialize_envelope, serialize_envelope


class Channel(virtual.Channel):
    """Solace Kombu channel."""

    do_restore = False

    from_transport_options = virtual.Channel.from_transport_options + (
        "environment",
        "namespace",
        "publish_confirm_mode",
        "receive_timeout",
    )

    environment = "default"
    namespace = "default"
    publish_confirm_mode = "async"
    receive_timeout = 1.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._delivery_refs: dict[str, object] = {}
        self._known_queues: set[str] = set()

    @property
    def adapter(self):
        return self.connection.adapter

    @property
    def options(self) -> SolaceTransportOptions:
        return self.connection.options

    def _queue_topic(self, queue: str) -> str:
        return queue_ingress_topic(
            queue,
            environment=self.options.environment,
            namespace=self.options.namespace,
        )

    def _new_queue(self, queue, **kwargs):
        self.adapter.ensure_queue(queue, durable=kwargs.get("durable", True))
        self.adapter.ensure_queue_subscription(queue, self._queue_topic(queue))
        self._known_queues.add(queue)

    def _has_queue(self, queue, **kwargs):
        return self.adapter.queue_exists(queue)

    def _put(self, queue, message, **kwargs):
        self._new_queue(queue)
        payload = serialize_envelope(message)
        self.adapter.publish(
            self._queue_topic(queue),
            payload,
            headers=message.get("headers"),
            properties=message.get("properties"),
            confirm_policy=self.publish_confirm_mode,
        )

    def _get(self, queue, timeout=None):
        self._new_queue(queue)
        timeout_ms = self._timeout_ms(timeout)
        inbound = self.adapter.receive(queue, timeout_ms=timeout_ms)
        message = deserialize_envelope(inbound.payload)
        delivery_tag = message.get("properties", {}).get("delivery_tag")
        if delivery_tag is not None:
            self._delivery_refs[delivery_tag] = inbound.delivery_ref
        return message

    def _purge(self, queue):
        strategy = self.options.purge_strategy
        if strategy in ("semp", "semp_then_receiver") and self.connection.management:
            try:
                return self.connection.management.purge_queue(queue)
            except ManagementUnavailable:
                if strategy == "semp":
                    raise
        if strategy in ("receiver", "semp_then_receiver"):
            return self.adapter.purge_by_receiving(
                queue,
                timeout_ms=self.options.purge_receive_timeout_ms,
                max_messages=self.options.purge_max_messages,
            )
        return 0

    def _size(self, queue):
        strategy = self.options.size_strategy
        if strategy in ("semp", "semp_then_browser") and self.connection.management:
            try:
                return self.connection.management.queue_size(queue)
            except ManagementUnavailable:
                if strategy == "semp":
                    raise
        if strategy in ("browser", "semp_then_browser"):
            return self.adapter.queue_size_by_browsing(
                queue, timeout_ms=self.options.browser_timeout_ms
            )
        return 0

    def _delete(self, queue, *args, **kwargs):
        self.adapter.close_receiver(queue)
        self._known_queues.discard(queue)

    def basic_ack(self, delivery_tag, multiple=False):
        try:
            delivery_ref = self._delivery_refs.pop(delivery_tag)
        except KeyError:
            return super().basic_ack(delivery_tag, multiple=multiple)
        try:
            self.adapter.ack(delivery_ref)
        except Exception as exc:
            self._delivery_refs[delivery_tag] = delivery_ref
            raise SettlementFailed(str(exc)) from exc
        ret = super().basic_ack(delivery_tag, multiple=multiple)
        self.qos._flush()
        return ret

    def basic_reject(self, delivery_tag, requeue=False):
        try:
            delivery_ref = self._delivery_refs.pop(delivery_tag)
        except KeyError:
            return super().basic_reject(delivery_tag, requeue=requeue)
        try:
            if requeue:
                self.adapter.settle_failed(delivery_ref)
            else:
                self.adapter.settle_rejected(delivery_ref)
        except Exception as exc:
            self._delivery_refs[delivery_tag] = delivery_ref
            raise SettlementFailed(str(exc)) from exc
        ret = super().basic_reject(delivery_tag, requeue=False)
        self.qos._flush()
        return ret

    def basic_recover(self, requeue=False):
        raise NotImplementedError("Solace transport does not republish unacked messages")

    def close(self):
        if not self.closed:
            for queue in list(self._known_queues):
                self.adapter.close_receiver(queue)
        return super().close()

    def _timeout_ms(self, timeout):
        value = self.receive_timeout if timeout is None else timeout
        if value is None:
            return None
        return int(max(value, 0) * 1000)


class Transport(virtual.Transport):
    """Solace Kombu transport."""

    Channel = Channel
    driver_type = "solace"
    driver_name = "solace-pubsubplus"
    default_port = 55555

    implements = virtual.Transport.implements.extend(
        asynchronous=False,
        exchange_type=frozenset(["direct", "topic"]),
        heartbeats=False,
    )

    connection_errors = virtual.Transport.connection_errors + (SettlementFailed,)
    channel_errors = virtual.Transport.channel_errors + (QueueUnavailable, ChannelError)

    def __init__(self, client, **kwargs):
        super().__init__(client, **kwargs)
        self.options = SolaceTransportOptions.from_connection(client)
        self.adapter = self._make_adapter()
        self.management = self._make_management_adapter()

    def establish_connection(self):
        self.adapter.connect(self._connection_settings())
        return super().establish_connection()

    def close_connection(self, connection):
        try:
            for channel in list(self.channels):
                channel.close()
            self.adapter.flush_publisher(self.options.publish_ack_timeout_ms)
        finally:
            self.adapter.close()
            super().close_connection(connection)

    @property
    def default_connection_params(self):
        return {"port": self.default_port, "hostname": "localhost"}

    def _make_adapter(self):
        options = self.client.transport_options
        adapter = options.get("adapter")
        if adapter is not None:
            return adapter
        factory = options.get("adapter_factory")
        if factory is not None:
            return factory()
        return PubSubPlusSolaceAdapter()

    def _make_management_adapter(self):
        options = self.client.transport_options
        adapter = options.get("management_adapter")
        if adapter is not None:
            return adapter
        factory = options.get("management_adapter_factory")
        if factory is not None:
            return factory()
        if self.options.semp_url:
            return SempV2ManagementAdapter(
                base_url=self.options.semp_url,
                vpn_name=self.options.vpn_name or self.client.virtual_host or "default",
                username=self.options.semp_username,
                password=self.options.semp_password,
                verify_tls=self.options.semp_verify_tls,
            )
        return None

    def _connection_settings(self) -> dict:
        settings = self.options.to_connection_settings(self.client)
        settings["port"] = settings["port"] or self.default_port
        return settings
