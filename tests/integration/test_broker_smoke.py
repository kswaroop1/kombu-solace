from __future__ import annotations

import os
import uuid

import pytest
from kombu import Connection, Exchange, Producer, Queue

from kombu_solace.management import SempV2ManagementAdapter
from kombu_solace.transport import Transport


pytestmark = pytest.mark.integration


def _integration_enabled() -> bool:
    return os.environ.get("SOLACE_RUN_INTEGRATION") == "1"


def _connection() -> Connection:
    return Connection(
        transport=Transport,
        hostname=os.environ.get("SOLACE_HOST", "localhost"),
        port=int(os.environ.get("SOLACE_PORT", "55588")),
        userid=os.environ.get("SOLACE_USERNAME", "sampleUser"),
        password=os.environ.get("SOLACE_PASSWORD", "samplePassword"),
        virtual_host=os.environ.get("SOLACE_VPN", "default"),
        transport_options={
            "environment": os.environ.get("SOLACE_ENVIRONMENT", "DEV1"),
            "namespace": os.environ.get("SOLACE_NAMESPACE", "kombu-solace-it"),
            "publish_confirm_mode": "sync",
            "publish_ack_timeout_ms": 10000,
            "publisher_buffer_capacity": 100,
            "receive_timeout": 1.0,
        },
    )


@pytest.mark.skipif(not _integration_enabled(), reason="Solace integration not enabled")
def test_real_broker_publish_basic_get_and_ack():
    connection = _connection()
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"it-celery-{suffix}"
    exchange = Exchange(f"it-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)

    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key=queue_name)
    message = channel.basic_get(queue_name)

    assert message is not None
    assert message.payload == {"ok": True}

    message.ack()
    connection.close()


@pytest.mark.skipif(not _integration_enabled(), reason="Solace integration not enabled")
def test_real_broker_semp_size_and_purge():
    semp_url = os.environ.get("SOLACE_SEMP_URL", "http://localhost:8080")
    management = SempV2ManagementAdapter(
        base_url=semp_url,
        vpn_name=os.environ.get("SOLACE_VPN", "default"),
        username=os.environ.get("SOLACE_SEMP_USERNAME", "admin"),
        password=os.environ.get("SOLACE_SEMP_PASSWORD", "admin"),
        verify_tls=os.environ.get("SOLACE_SEMP_VERIFY_TLS", "false").lower()
        not in ("0", "false", "no"),
    )
    connection = _connection()
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"it-semp-{suffix}"
    exchange = Exchange(f"it-semp-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)

    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"ok": True}, routing_key=queue_name)
    connection.close()

    assert management.queue_size(queue_name) == 1
    assert management.purge_queue(queue_name) == 1
    assert management.queue_size(queue_name) == 0


@pytest.mark.skipif(not _integration_enabled(), reason="Solace integration not enabled")
def test_real_broker_redelivers_unacked_message_after_channel_close():
    suffix = uuid.uuid4().hex
    queue_name = f"it-redeliver-{suffix}"
    exchange = Exchange(f"it-redeliver-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)

    connection = _connection()
    channel = connection.channel()
    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"redeliver": True}, routing_key=queue_name)
    message = channel.basic_get(queue_name)

    assert message is not None
    assert message.payload == {"redeliver": True}
    connection.close()

    connection = _connection()
    channel = connection.channel()
    queue(channel).declare()
    redelivered = channel.basic_get(queue_name)

    assert redelivered is not None
    assert redelivered.payload == {"redeliver": True}
    redelivered.ack()
    connection.close()


@pytest.mark.skipif(not _integration_enabled(), reason="Solace integration not enabled")
def test_real_broker_reject_requeue_redelivers_message():
    connection = _connection()
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"it-nack-{suffix}"
    exchange = Exchange(f"it-nack-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)

    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"nack": True}, routing_key=queue_name)
    message = channel.basic_get(queue_name)

    assert message is not None
    message.reject(requeue=True)

    redelivered = channel.basic_get(queue_name)
    assert redelivered is not None
    assert redelivered.payload == {"nack": True}
    redelivered.ack()
    connection.close()


@pytest.mark.skipif(not _integration_enabled(), reason="Solace integration not enabled")
def test_real_broker_reject_without_requeue_does_not_redeliver_message():
    connection = _connection()
    channel = connection.channel()
    suffix = uuid.uuid4().hex
    queue_name = f"it-reject-{suffix}"
    exchange = Exchange(f"it-reject-tasks-{suffix}", type="direct")
    queue = Queue(queue_name, exchange=exchange, routing_key=queue_name)

    queue(channel).declare()
    Producer(channel, exchange=exchange).publish({"reject": True}, routing_key=queue_name)
    message = channel.basic_get(queue_name)

    assert message is not None
    message.reject(requeue=False)

    assert channel.basic_get(queue_name) is None
    connection.close()
