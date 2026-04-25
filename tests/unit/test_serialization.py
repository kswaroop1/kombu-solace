from __future__ import annotations

from kombu_solace.serialization import deserialize_envelope, serialize_envelope


def test_message_envelope_round_trips():
    message = {
        "body": "payload",
        "headers": {"task": "proj.tasks.add"},
        "properties": {
            "delivery_tag": "tag-1",
            "delivery_info": {"exchange": "tasks", "routing_key": "add"},
            "correlation_id": "cid",
            "reply_to": "reply-queue",
        },
        "content-type": "application/json",
        "content-encoding": "utf-8",
    }

    assert deserialize_envelope(serialize_envelope(message)) == message


def test_message_envelope_accepts_bytes_payload():
    payload = serialize_envelope({"body": "payload", "properties": {}}).encode("utf-8")

    assert deserialize_envelope(payload)["body"] == "payload"

