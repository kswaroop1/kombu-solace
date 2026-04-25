"""Transport-specific exceptions and error mapping helpers."""

from __future__ import annotations


class SolaceTransportError(Exception):
    """Base class for transport-level Solace failures."""


class SolaceConnectionError(SolaceTransportError):
    """Connection-level Solace failure."""


class SolaceChannelError(SolaceTransportError):
    """Channel-level Solace failure."""


class QueueUnavailable(SolaceChannelError):
    """Raised when a queue is unavailable and cannot be created."""


class PublishFailed(SolaceConnectionError):
    """Raised when persistent publish confirmation fails."""


class SettlementFailed(SolaceConnectionError):
    """Raised when ack or settlement fails."""


class ManagementUnavailable(SolaceChannelError):
    """Raised when optional management operations are unavailable."""


def map_connection_error(exc: Exception, operation: str) -> SolaceConnectionError:
    """Normalize a lower-level exception as a Kombu connection-level failure."""

    if isinstance(exc, SolaceConnectionError):
        return exc
    return SolaceConnectionError(f"{operation} failed: {exc}")


def map_channel_error(exc: Exception, operation: str) -> SolaceChannelError:
    """Normalize a lower-level exception as a Kombu channel-level failure."""

    if isinstance(exc, SolaceChannelError):
        return exc
    return SolaceChannelError(f"{operation} failed: {exc}")
