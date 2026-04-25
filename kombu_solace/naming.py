"""Naming helpers for Solace resources used by the Kombu transport."""

from __future__ import annotations

import base64
import hashlib

MAX_SOLACE_TOPIC_BYTES = 250
MAX_SOLACE_TOPIC_LEVELS = 128


def _b64url(value: str) -> str:
    raw = value.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def queue_ingress_topic(
    queue_name: str,
    *,
    environment: str = "default",
    namespace: str = "default",
) -> str:
    """Return the internal topic used to publish to one Kombu queue.

    Solace topics are slash-delimited and treat wildcard characters specially in
    subscriptions. Encoding the queue name keeps arbitrary Kombu queue names from
    changing the topic structure.
    """

    encoded_environment = _b64url(environment or "default")
    encoded_namespace = _b64url(namespace or "default")
    encoded_queue = _b64url(queue_name)
    topic = f"_kombu/{encoded_environment}/{encoded_namespace}/queue/{encoded_queue}"

    if _is_valid_topic(topic):
        return topic

    digest = hashlib.sha256(queue_name.encode("utf-8")).hexdigest()
    topic = f"_kombu/{encoded_environment}/{encoded_namespace}/queue/sha256-{digest}"
    if not _is_valid_topic(topic):
        raise ValueError("internal Solace topic exceeds Solace topic limits")
    return topic


def _is_valid_topic(topic: str) -> bool:
    return (
        len(topic.encode("utf-8")) <= MAX_SOLACE_TOPIC_BYTES
        and topic.count("/") + 1 <= MAX_SOLACE_TOPIC_LEVELS
        and "\x00" not in topic
    )
