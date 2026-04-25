from __future__ import annotations

import pytest

from kombu_solace.wildcards import amqp_topic_binding_to_solace_subscription


@pytest.mark.parametrize(
    ("binding_key", "subscription"),
    [
        ("task.created", "task/created"),
        ("task.*", "task/*"),
        ("task.#", "task/>"),
        ("tenant.*.task.#", "tenant/*/task/>"),
    ],
)
def test_safe_amqp_topic_bindings_translate_to_solace_subscriptions(
    binding_key, subscription
):
    assert amqp_topic_binding_to_solace_subscription(binding_key) == subscription


@pytest.mark.parametrize(
    "binding_key",
    [
        "",
        "#",
        "#.task",
        "task.#.created",
        "task..created",
        "task/created",
        "task.>",
        "task.literal*",
    ],
)
def test_unsafe_amqp_topic_bindings_are_rejected(binding_key):
    with pytest.raises(ValueError):
        amqp_topic_binding_to_solace_subscription(binding_key)

