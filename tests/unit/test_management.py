from __future__ import annotations

import json
from unittest.mock import Mock, patch

from kombu_solace.management import SempV2ManagementAdapter


def test_semp_queue_size_parses_msgs_count():
    adapter = SempV2ManagementAdapter(
        base_url="https://broker.example.com:943",
        vpn_name="nonprod",
        username="admin",
        password="secret",
    )
    response = {
        "data": {
            "collections": {
                "msgs": {
                    "count": 17,
                }
            }
        }
    }

    with patch("kombu_solace.management.urlopen", return_value=_json_response(response)) as urlopen:
        assert adapter.queue_size("DEV1/orders/celery") == 17

    request = urlopen.call_args.args[0]
    assert "queueName%2Cmsgs.count" in request.full_url
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


def _json_response(payload):
    response = Mock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    return response
