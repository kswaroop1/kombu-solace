from __future__ import annotations

import os

import pytest

from kombu_solace.management import SempV2ManagementAdapter


TEST_QUEUE_PREFIXES = ("it-", "it.", "perf-", "soak-")


@pytest.fixture(autouse=True)
def cleanup_solace_test_queues():
    yield
    if os.environ.get("SOLACE_CLEANUP_QUEUES", "1").lower() in ("0", "false", "no"):
        return
    if not any(
        os.environ.get(name) == "1"
        for name in (
            "SOLACE_RUN_INTEGRATION",
            "SOLACE_RUN_CELERY",
            "SOLACE_RUN_CELERY_INTERRUPT",
            "SOLACE_RUN_PERFORMANCE",
            "SOLACE_RUN_SOAK",
        )
    ):
        return
    adapter = SempV2ManagementAdapter(
        base_url=os.environ.get("SOLACE_SEMP_URL", "http://localhost:8080"),
        vpn_name=os.environ.get("SOLACE_VPN", "default"),
        username=os.environ.get("SOLACE_SEMP_USERNAME", "admin"),
        password=os.environ.get("SOLACE_SEMP_PASSWORD", "admin"),
        timeout=2,
        verify_tls=os.environ.get("SOLACE_SEMP_VERIFY_TLS", "false").lower()
        not in ("0", "false", "no"),
    )
    for queue_name in _list_test_queues(adapter):
        try:
            adapter.delete_queue(queue_name)
        except Exception:
            pass


def _list_test_queues(adapter: SempV2ManagementAdapter) -> list[str]:
    path = f"/SEMP/v2/config/msgVpns/{adapter.vpn_name}/queues?count=1000"
    response = adapter._request_json("GET", path)
    queues = []
    for item in response.get("data", []):
        queue_name = item.get("queueName", "")
        if queue_name.startswith(TEST_QUEUE_PREFIXES):
            queues.append(queue_name)
    return queues
