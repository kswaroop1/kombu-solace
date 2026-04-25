"""Serialization helpers for Kombu message envelopes."""

from __future__ import annotations

from kombu.utils.json import dumps, loads


def serialize_envelope(message: dict) -> str:
    """Serialize a Kombu virtual message envelope for Solace payload storage."""

    return dumps(message)


def deserialize_envelope(payload: bytes | str | dict) -> dict:
    """Deserialize a Solace payload back into a Kombu virtual message envelope."""

    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    value = loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Solace payload did not contain a Kombu message envelope")
    return value

