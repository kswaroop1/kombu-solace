from __future__ import annotations

import pytest

from kombu_solace.naming import physical_queue_name, queue_ingress_topic


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


def test_queue_ingress_topic_can_use_corporate_topic_root():
    topic = queue_ingress_topic(
        "celery",
        environment="DEV1",
        namespace="tasks",
        application="orders",
        topic_prefix="corp/nonprod",
    )

    assert topic.startswith("corp/nonprod/orders/DEV1/_kombu/tasks/queue/")


def test_queue_ingress_topic_encodes_unsafe_topic_root_segments():
    topic = queue_ingress_topic(
        "celery",
        environment="DEV 1",
        namespace="tasks namespace",
        application="orders/app",
        topic_prefix="corp root/nonprod",
    )

    assert topic.startswith("b64-Y29ycCByb290/nonprod/b64-b3JkZXJzL2FwcA/")
    assert "/b64-REVWIDE/" in topic
    assert "/b64-dGFza3MgbmFtZXNwYWNl/" in topic


def test_queue_ingress_topic_supports_application_without_topic_prefix():
    topic = queue_ingress_topic("celery", environment="DEV1", namespace="tasks", application="orders")

    assert topic.startswith("orders/DEV1/_kombu/tasks/queue/")


def test_physical_queue_name_defaults_to_logical_queue_name():
    assert physical_queue_name("celery", environment="DEV1") == "celery"


def test_physical_queue_name_uses_prefix_application_environment_convention():
    assert (
        physical_queue_name(
            "celery",
            environment="DEV1",
            application="orders",
            queue_name_prefix="corp",
        )
        == "corp.orders.DEV1.celery"
    )


def test_physical_queue_name_supports_custom_template():
    assert (
        physical_queue_name(
            "celery",
            environment="UAT3",
            application="billing",
            queue_name_prefix="corp",
            queue_name_template="{prefix}.{application}.{environment}.{queue}",
        )
        == "corp.billing.UAT3.celery"
    )


def test_physical_queue_name_encodes_unsafe_segments():
    name = physical_queue_name(
        "queue/with/slashes",
        environment="DEV1",
        application="orders",
        queue_name_prefix="corp",
    )

    assert name.startswith("corp.orders.DEV1.b64-")
    assert "/" not in name


def test_physical_queue_name_hashes_long_logical_names_to_fit():
    name = physical_queue_name(
        "q" * 1000,
        environment="DEV1",
        application="orders",
        queue_name_prefix="corp",
    )

    assert name.startswith("corp.orders.DEV1.sha256-")
    assert len(name.encode("utf-8")) <= 250


def test_physical_queue_name_custom_template_hashes_long_logical_name():
    name = physical_queue_name(
        "q" * 1000,
        environment="DEV1",
        application="orders",
        queue_name_prefix="corp",
        queue_name_template="{prefix}.{application}.{environment}.{queue}",
    )

    assert name.startswith("corp.orders.DEV1.sha256-")


def test_physical_queue_name_rejects_empty_or_unfittable_names():
    with pytest.raises(ValueError, match="physical Solace queue name"):
        physical_queue_name("")

    with pytest.raises(ValueError, match="physical Solace queue name"):
        physical_queue_name(
            "q" * 1000,
            queue_name_template=("x" * 300) + ".{queue}",
        )
