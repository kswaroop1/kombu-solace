from __future__ import annotations

import kombu_solace
from kombu.transport import TRANSPORT_ALIASES


def test_register_transport_adds_solace_alias():
    kombu_solace.register_transport()

    assert TRANSPORT_ALIASES["solace"] == "kombu_solace.transport:Transport"

