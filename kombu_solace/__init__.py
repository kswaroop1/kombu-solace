"""Kombu transport for Solace PubSub+."""

__version__ = "0.0.0"


def register_transport() -> None:
    """Register the `solace` URL scheme with Kombu in the current process."""

    from kombu.transport import TRANSPORT_ALIASES

    TRANSPORT_ALIASES.setdefault("solace", "kombu_solace.transport:Transport")


register_transport()
