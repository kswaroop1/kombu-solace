"""Pythonic transport option parsing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


PublishConfirmMode = Literal["async", "sync"]
BackPressureStrategy = Literal["wait", "reject", "elastic"]
SizeStrategy = Literal["semp_then_browser", "semp", "browser", "disabled"]
PurgeStrategy = Literal["semp_then_receiver", "semp", "receiver", "disabled"]
RoutingMode = Literal["kombu", "native"]


@dataclass(frozen=True)
class SolaceTransportOptions:
    """Validated transport options used by the Solace Kombu transport."""

    vpn_name: str | None = None
    environment: str = "default"
    namespace: str = "default"
    create_missing_queues: bool = True
    routing_mode: RoutingMode = "kombu"
    publish_confirm_mode: PublishConfirmMode = "async"
    publish_ack_timeout_ms: int = 30000
    publisher_back_pressure_strategy: BackPressureStrategy = "wait"
    allow_elastic_back_pressure: bool = False
    publisher_buffer_capacity: int = 1000
    receive_timeout: float = 1.0
    enable_nacks: bool = True
    transport_scheme: str = "tcp"
    semp_url: str | None = None
    semp_username: str | None = None
    semp_password: str | None = None
    semp_verify_tls: bool = True
    size_strategy: SizeStrategy = "semp_then_browser"
    purge_strategy: PurgeStrategy = "semp_then_receiver"
    browser_timeout_ms: int = 100
    purge_receive_timeout_ms: int = 100
    purge_max_messages: int | None = None

    @classmethod
    def from_connection(cls, client) -> "SolaceTransportOptions":
        options = dict(client.transport_options or {})
        return cls(
            vpn_name=options.get("vpn_name") or client.virtual_host,
            environment=options.get("environment", "default"),
            namespace=options.get("namespace", "default"),
            create_missing_queues=options.get("create_missing_queues", True),
            routing_mode=options.get("routing_mode", "kombu"),
            publish_confirm_mode=options.get("publish_confirm_mode", "async"),
            publish_ack_timeout_ms=options.get("publish_ack_timeout_ms", 30000),
            publisher_back_pressure_strategy=options.get(
                "publisher_back_pressure_strategy", "wait"
            ),
            allow_elastic_back_pressure=options.get(
                "allow_elastic_back_pressure", False
            ),
            publisher_buffer_capacity=options.get("publisher_buffer_capacity", 1000),
            receive_timeout=options.get("receive_timeout", 1.0),
            enable_nacks=options.get("enable_nacks", True),
            transport_scheme=options.get("transport_scheme", "tcp"),
            semp_url=options.get("semp_url") or options.get("management_url"),
            semp_username=options.get("semp_username")
            or options.get("management_username"),
            semp_password=options.get("semp_password")
            or options.get("management_password"),
            semp_verify_tls=options.get("semp_verify_tls", True),
            size_strategy=options.get("size_strategy", "semp_then_browser"),
            purge_strategy=options.get("purge_strategy", "semp_then_receiver"),
            browser_timeout_ms=options.get("browser_timeout_ms", 100),
            purge_receive_timeout_ms=options.get("purge_receive_timeout_ms", 100),
            purge_max_messages=options.get("purge_max_messages"),
        ).validate()

    def to_connection_settings(self, client) -> dict[str, Any]:
        return {
            "hostname": client.hostname,
            "port": client.port,
            "userid": client.userid,
            "password": client.password,
            "virtual_host": client.virtual_host,
            "vpn_name": self.vpn_name,
            "environment": self.environment,
            "namespace": self.namespace,
            "create_missing_queues": self.create_missing_queues,
            "routing_mode": self.routing_mode,
            "publish_confirm_mode": self.publish_confirm_mode,
            "publish_ack_timeout_ms": self.publish_ack_timeout_ms,
            "enable_nacks": self.enable_nacks,
            "publisher_back_pressure_strategy": self.publisher_back_pressure_strategy,
            "allow_elastic_back_pressure": self.allow_elastic_back_pressure,
            "publisher_buffer_capacity": self.publisher_buffer_capacity,
            "receive_timeout": self.receive_timeout,
            "transport_scheme": self.transport_scheme,
            "semp_url": self.semp_url,
            "semp_username": self.semp_username,
            "semp_password": self.semp_password,
            "semp_verify_tls": self.semp_verify_tls,
            "size_strategy": self.size_strategy,
            "purge_strategy": self.purge_strategy,
            "browser_timeout_ms": self.browser_timeout_ms,
            "purge_receive_timeout_ms": self.purge_receive_timeout_ms,
            "purge_max_messages": self.purge_max_messages,
        }

    def validate(self) -> "SolaceTransportOptions":
        if self.routing_mode != "kombu":
            raise ValueError("only routing_mode='kombu' is implemented")
        if self.publish_confirm_mode not in ("async", "sync"):
            raise ValueError("publish_confirm_mode must be 'async' or 'sync'")
        if self.publisher_back_pressure_strategy not in ("wait", "reject", "elastic"):
            raise ValueError(
                "publisher_back_pressure_strategy must be 'wait', 'reject', or 'elastic'"
            )
        if (
            self.publisher_back_pressure_strategy == "elastic"
            and not self.allow_elastic_back_pressure
        ):
            raise ValueError(
                "elastic back-pressure is unbounded; set allow_elastic_back_pressure "
                "support before enabling it"
            )
        if self.size_strategy not in ("semp_then_browser", "semp", "browser", "disabled"):
            raise ValueError("invalid size_strategy")
        if self.purge_strategy not in (
            "semp_then_receiver",
            "semp",
            "receiver",
            "disabled",
        ):
            raise ValueError("invalid purge_strategy")
        if self.publisher_buffer_capacity <= 0:
            raise ValueError("publisher_buffer_capacity must be positive")
        if self.browser_timeout_ms < 0:
            raise ValueError("browser_timeout_ms must be non-negative")
        if self.purge_receive_timeout_ms < 0:
            raise ValueError("purge_receive_timeout_ms must be non-negative")
        return self
