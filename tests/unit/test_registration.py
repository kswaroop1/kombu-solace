from __future__ import annotations

import kombu_solace
from kombu.transport import TRANSPORT_ALIASES, resolve_transport


def test_register_transport_adds_solace_alias():
    kombu_solace.register_transport()

    assert TRANSPORT_ALIASES["solace"] == "kombu_solace.transport:Transport"


def test_solace_url_resolves_after_package_import():
    kombu_solace.register_transport()

    transport = resolve_transport("solace")

    assert transport.__module__ == "kombu_solace.transport"
    assert transport.__name__ == "Transport"
