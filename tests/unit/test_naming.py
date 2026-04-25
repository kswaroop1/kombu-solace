from __future__ import annotations

import pytest

from kombu_solace.naming import queue_ingress_topic


@pytest.mark.parametrize(
    "queue_name",
    [
        "celery",
        "tasks.high-priority",
        "queue/with/slashes",
        "queue*with>wildcards",
        "queue with spaces",
        "unicode-\u2603",
    ],
)
def test_queue_ingress_topic_is_single_encoded_queue_level(queue_name):
    topic = queue_ingress_topic(queue_name, environment="DEV1", namespace="test")

    assert topic.startswith("_kombu/")
    assert "/queue/" in topic
    assert topic.count("/") == 4
    encoded_queue = topic.rsplit("/", 1)[-1]
    assert "*" not in encoded_queue
    assert ">" not in encoded_queue
    assert "\x00" not in encoded_queue
    assert len(topic.encode("utf-8")) <= 250


def test_queue_ingress_topic_hashes_long_names_to_fit_solace_limit():
    topic = queue_ingress_topic("q" * 1000, environment="DEV1", namespace="test")

    assert topic.rsplit("/", 1)[-1].startswith("sha256-")
    assert len(topic.encode("utf-8")) <= 250


def test_queue_ingress_topic_rejects_namespace_that_cannot_fit():
    with pytest.raises(ValueError):
        queue_ingress_topic("celery", environment="DEV1", namespace="n" * 1000)


def test_queue_ingress_topic_uses_environment_as_destination_root():
    dev_topic = queue_ingress_topic("celery", environment="DEV1", namespace="orders")
    uat_topic = queue_ingress_topic("celery", environment="UAT3", namespace="orders")

    assert dev_topic != uat_topic
    assert dev_topic.split("/")[1] != uat_topic.split("/")[1]
