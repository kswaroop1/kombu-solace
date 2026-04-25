from __future__ import annotations

from collections import deque
from threading import Condition

import pytest
from solace.messaging.config.solace_properties import service_properties
from solace.messaging.config.solace_properties import transport_layer_properties
from solace.messaging.publisher.persistent_message_publisher import (
    MessagePublishReceiptListener,
)

from kombu_solace.adapter import _PublishReceiptListener, build_service_properties
from kombu_solace.adapter import PubSubPlusSolaceAdapter
from kombu_solace.errors import PublishFailed


class FakePublishReceipt:
    def __init__(self, *, is_persisted=True, exception=None):
        self.is_persisted = is_persisted
        self.exception = exception


def test_build_service_properties_uses_solace_property_keys():
    props = build_service_properties(
        {
            "hostname": "broker.example.com",
            "port": 55443,
            "transport_scheme": "tcps",
            "vpn_name": "prod-vpn",
        }
    )

    assert props[transport_layer_properties.HOST] == "tcps://broker.example.com:55443"
    assert props[service_properties.VPN_NAME] == "prod-vpn"


def test_build_service_properties_preserves_explicit_host_uri():
    props = build_service_properties(
        {
            "hostname": "tcp://broker.example.com:55555",
            "port": 1234,
            "vpn_name": "default",
        }
    )

    assert props[transport_layer_properties.HOST] == "tcp://broker.example.com:55555"


def test_publish_receipt_listener_matches_solace_required_type():
    listener = _PublishReceiptListener(failures=[])

    assert isinstance(listener, MessagePublishReceiptListener)


def test_publish_receipt_success_decrements_pending_count():
    failures = deque()
    condition = Condition()
    pending = [1]
    listener = _PublishReceiptListener(
        failures,
        condition=condition,
        pending_counter=pending,
    )

    listener.on_publish_receipt(FakePublishReceipt(is_persisted=True))

    assert pending == [0]
    assert not failures


def test_publish_receipt_failure_records_failure_and_decrements_pending_count():
    failures = deque()
    condition = Condition()
    pending = [1]
    listener = _PublishReceiptListener(
        failures,
        condition=condition,
        pending_counter=pending,
    )

    listener.on_publish_receipt(
        FakePublishReceipt(is_persisted=False, exception=RuntimeError("rejected"))
    )

    assert pending == [0]
    assert isinstance(failures[0], RuntimeError)


def test_pending_publish_receipt_failure_surfaces_on_flush():
    adapter = PubSubPlusSolaceAdapter()
    adapter._publish_failures.append(RuntimeError("broker rejected publish"))

    try:
        adapter.flush_publisher(timeout_ms=100)
    except PublishFailed as exc:
        assert "broker rejected publish" in str(exc)
    else:
        raise AssertionError("expected PublishFailed")


def test_flush_publisher_times_out_with_pending_receipts():
    adapter = PubSubPlusSolaceAdapter()
    adapter._pending_publishes[0] = 1

    with pytest.raises(PublishFailed, match="timed out waiting for 1"):
        adapter.flush_publisher(timeout_ms=1)
