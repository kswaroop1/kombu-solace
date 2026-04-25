from __future__ import annotations

import pytest
from kombu import Connection

from kombu_solace.config import SolaceTransportOptions


def test_transport_options_from_connection_supports_environment_and_semp_aliases():
    connection = Connection(
        "solace://user:pass@broker.example.com:55555/nonprod",
        transport_options={
            "environment": "DEV1",
            "namespace": "orders",
            "application": "fulfilment",
            "queue_name_prefix": "corp",
            "topic_prefix": "corp/nonprod",
            "management_url": "https://broker.example.com:943",
            "management_username": "admin",
            "management_password": "secret",
        },
    )

    options = SolaceTransportOptions.from_connection(connection)

    assert options.vpn_name == "nonprod"
    assert options.environment == "DEV1"
    assert options.namespace == "orders"
    assert options.application == "fulfilment"
    assert options.queue_name_prefix == "corp"
    assert options.topic_prefix == "corp/nonprod"
    assert options.semp_url == "https://broker.example.com:943"
    assert options.semp_username == "admin"
    assert options.semp_password == "secret"


def test_elastic_back_pressure_requires_explicit_opt_in():
    connection = Connection(
        transport_options={"publisher_back_pressure_strategy": "elastic"},
    )

    with pytest.raises(ValueError, match="elastic back-pressure"):
        SolaceTransportOptions.from_connection(connection)


def test_elastic_back_pressure_can_be_explicitly_enabled():
    connection = Connection(
        transport_options={
            "publisher_back_pressure_strategy": "elastic",
            "allow_elastic_back_pressure": True,
        },
    )

    options = SolaceTransportOptions.from_connection(connection)

    assert options.publisher_back_pressure_strategy == "elastic"


def test_queue_name_template_is_validated():
    connection = Connection(
        transport_options={"queue_name_template": "{missing}.{queue}"},
    )

    with pytest.raises(ValueError, match="unknown queue_name_template field"):
        SolaceTransportOptions.from_connection(connection)
