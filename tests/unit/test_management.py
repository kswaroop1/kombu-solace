from __future__ import annotations

import json
from unittest.mock import Mock, patch
from urllib.error import URLError

import pytest
from kombu_solace.errors import ManagementUnavailable
from kombu_solace.management import SempV2ManagementAdapter
from kombu_solace.management import _extract_message_id


def test_semp_queue_size_parses_msgs_count():
    adapter = SempV2ManagementAdapter(
        base_url="https://broker.example.com:943",
        vpn_name="nonprod",
        username="admin",
        password="secret",
    )
    response = {"data": [{"msgId": i} for i in range(17)]}

    with patch("kombu_solace.management.urlopen", return_value=_json_response(response)) as urlopen:
        assert adapter.queue_size("DEV1/orders/celery") == 17

    request = urlopen.call_args.args[0]
    assert "/SEMP/v2/action/msgVpns/nonprod/queues/" in request.full_url
    assert "DEV1%2Forders%2Fcelery" in request.full_url
    assert request.get_header("Authorization").startswith("Basic ")


def test_semp_purge_lists_and_deletes_messages():
    adapter = SempV2ManagementAdapter(
        base_url="https://broker.example.com:943",
        vpn_name="nonprod",
    )
    responses = [
        _json_response({"data": [{"msgId": 1}, {"msgId": 2}]}),
        _json_response({}),
        _json_response({}),
        _json_response({"data": []}),
    ]

    with patch("kombu_solace.management.urlopen", side_effect=responses) as urlopen:
        assert adapter.purge_queue("celery") == 2

    methods = [call.args[0].get_method() for call in urlopen.call_args_list]
    assert methods == ["GET", "PUT", "PUT", "GET"]


def test_semp_delete_queue_uses_config_endpoint():
    adapter = SempV2ManagementAdapter(
        base_url="https://broker.example.com:943",
        vpn_name="nonprod",
    )

    with patch("kombu_solace.management.urlopen", return_value=_json_response({})) as urlopen:
        adapter.delete_queue("DEV1.orders.celery")

    request = urlopen.call_args.args[0]
    assert request.get_method() == "DELETE"
    assert "/SEMP/v2/config/msgVpns/nonprod/queues/" in request.full_url
    assert "DEV1.orders.celery" in request.full_url


def test_semp_list_messages_accepts_single_data_object():
    adapter = SempV2ManagementAdapter(base_url="https://broker.example.com:943", vpn_name="vpn")

    with patch("kombu_solace.management.urlopen", return_value=_json_response({"data": {"msgId": 1}})):
        assert adapter.queue_size("celery") == 1


def test_semp_list_messages_rejects_unexpected_data_shape():
    adapter = SempV2ManagementAdapter(base_url="https://broker.example.com:943", vpn_name="vpn")

    with patch("kombu_solace.management.urlopen", return_value=_json_response({"data": "bad"})):
        with pytest.raises(ManagementUnavailable, match="unexpected"):
            adapter.queue_size("celery")


def test_semp_purge_requires_message_id():
    adapter = SempV2ManagementAdapter(base_url="https://broker.example.com:943", vpn_name="vpn")

    with patch("kombu_solace.management.urlopen", return_value=_json_response({"data": [{}]})):
        with pytest.raises(ManagementUnavailable, match="message id"):
            adapter.purge_queue("celery")


def test_semp_request_without_auth_uses_default_tls_context_and_empty_response():
    adapter = SempV2ManagementAdapter(
        base_url="https://broker.example.com:943",
        vpn_name="vpn",
        verify_tls=True,
    )

    with patch("kombu_solace.management.urlopen", return_value=_raw_response(b"")) as urlopen:
        assert adapter._request_json("GET", "/path") == {}

    request = urlopen.call_args.args[0]
    assert request.get_header("Authorization") is None
    assert urlopen.call_args.kwargs["context"] is None


def test_semp_request_wraps_transport_and_json_errors():
    adapter = SempV2ManagementAdapter(base_url="https://broker.example.com:943", vpn_name="vpn")

    with patch("kombu_solace.management.urlopen", side_effect=URLError("down")):
        with pytest.raises(ManagementUnavailable, match="down"):
            adapter._request_json("GET", "/path")

    with patch("kombu_solace.management.urlopen", return_value=_raw_response(b"not-json")):
        with pytest.raises(ManagementUnavailable, match="not JSON"):
            adapter._request_json("GET", "/path")


@pytest.mark.parametrize("key", ["msg-id", "messageId", "message-id", "id"])
def test_extract_message_id_supports_known_semp_keys(key):
    assert _extract_message_id({key: 123}) == "123"


def test_extract_message_id_returns_none_when_missing():
    assert _extract_message_id({}) is None


def _json_response(payload):
    return _raw_response(json.dumps(payload).encode("utf-8"))


def _raw_response(payload):
    response = Mock()
    response.read.return_value = payload
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    return response
