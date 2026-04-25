"""Naming helpers for Solace resources used by the Kombu transport."""

from __future__ import annotations

import base64
import hashlib
import re

MAX_SOLACE_TOPIC_BYTES = 250
MAX_SOLACE_TOPIC_LEVELS = 128
MAX_SOLACE_QUEUE_NAME_BYTES = 250
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _b64url(value: str) -> str:
    raw = value.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def queue_ingress_topic(
    queue_name: str,
    *,
    environment: str = "default",
    namespace: str = "default",
    application: str | None = None,
    topic_prefix: str | None = None,
) -> str:
    """Return the internal topic used to publish to one Kombu queue.

    Solace topics are slash-delimited and treat wildcard characters specially in
    subscriptions. Encoding the queue name keeps arbitrary Kombu queue names from
    changing the topic structure.
    """

    root = _internal_topic_root(
        environment=environment,
        namespace=namespace,
        application=application,
        topic_prefix=topic_prefix,
    )
    encoded_queue = _b64url(queue_name)
    topic = f"{root}/queue/{encoded_queue}"

    if _is_valid_topic(topic):
        return topic

    digest = hashlib.sha256(queue_name.encode("utf-8")).hexdigest()
    topic = f"{root}/queue/sha256-{digest}"
    if not _is_valid_topic(topic):
        raise ValueError("internal Solace topic exceeds Solace topic limits")
    return topic


def physical_queue_name(
    logical_queue_name: str,
    *,
    environment: str = "default",
    application: str | None = None,
    queue_name_prefix: str | None = None,
    queue_name_template: str | None = None,
) -> str:
    """Return the Solace queue resource name for a logical Kombu queue.

    Without an explicit application, prefix, or template this returns the logical
    name unchanged to avoid surprising existing Kombu/Celery deployments.
    """

    if queue_name_template:
        name = queue_name_template.format(
            **_queue_template_fields(
                logical_queue_name,
                environment=environment,
                application=application,
                queue_name_prefix=queue_name_prefix,
            )
        )
    elif queue_name_prefix or application:
        parts = [
            queue_name_prefix,
            application,
            environment or "default",
            logical_queue_name,
        ]
        name = ".".join(_queue_segment(part) for part in parts if part)
    else:
        name = logical_queue_name

    if _is_valid_queue_name(name):
        return name

    digest = hashlib.sha256(logical_queue_name.encode("utf-8")).hexdigest()
    if queue_name_template:
        name = queue_name_template.format(
            **_queue_template_fields(
                f"sha256-{digest}",
                environment=environment,
                application=application,
                queue_name_prefix=queue_name_prefix,
                logical_queue_name=f"sha256-{digest}",
            )
        )
    elif queue_name_prefix or application:
        parts = [
            queue_name_prefix,
            application,
            environment or "default",
            f"sha256-{digest}",
        ]
        name = ".".join(_queue_segment(part) for part in parts if part)
    if not _is_valid_queue_name(name):
        raise ValueError("physical Solace queue name exceeds safe queue name limits")
    return name


def _internal_topic_root(
    *,
    environment: str,
    namespace: str,
    application: str | None,
    topic_prefix: str | None,
) -> str:
    if topic_prefix or application:
        levels = [
            *_topic_path_levels(topic_prefix),
            _topic_segment(application) if application else None,
            _topic_segment(environment or "default"),
            "_kombu",
            _topic_segment(namespace or "default"),
        ]
        return "/".join(level for level in levels if level)
    return "/".join(
        [
            "_kombu",
            _topic_segment(environment or "default"),
            _topic_segment(namespace or "default"),
        ]
    )


def _topic_path_levels(path: str | None) -> list[str]:
    if not path:
        return []
    return [_topic_segment(level) for level in path.split("/") if level]


def _topic_segment(value: str) -> str:
    return value if SAFE_NAME_RE.match(value) else f"b64-{_b64url(value)}"


def _queue_segment(value: str) -> str:
    return value if SAFE_NAME_RE.match(value) else f"b64-{_b64url(value)}"


def _queue_template_fields(
    queue: str,
    *,
    environment: str,
    application: str | None,
    queue_name_prefix: str | None,
    logical_queue_name: str | None = None,
) -> dict[str, str]:
    return {
        "prefix": _queue_segment(queue_name_prefix) if queue_name_prefix else "",
        "app": _queue_segment(application) if application else "",
        "application": _queue_segment(application) if application else "",
        "env": _queue_segment(environment or "default"),
        "environment": _queue_segment(environment or "default"),
        "queue": _queue_segment(queue),
        "logical_queue": logical_queue_name or queue,
    }


def _is_valid_topic(topic: str) -> bool:
    return (
        len(topic.encode("utf-8")) <= MAX_SOLACE_TOPIC_BYTES
        and topic.count("/") + 1 <= MAX_SOLACE_TOPIC_LEVELS
        and "\x00" not in topic
    )


def _is_valid_queue_name(name: str) -> bool:
    return (
        bool(name)
        and len(name.encode("utf-8")) <= MAX_SOLACE_QUEUE_NAME_BYTES
        and "\x00" not in name
    )
