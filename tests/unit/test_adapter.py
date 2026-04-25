from __future__ import annotations

from solace.messaging.config.solace_properties import service_properties
from solace.messaging.config.solace_properties import transport_layer_properties

from kombu_solace.adapter import build_service_properties


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

