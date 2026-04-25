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
