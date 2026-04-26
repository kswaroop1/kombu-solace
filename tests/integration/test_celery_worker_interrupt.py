from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
import uuid

import pytest
from celery import Celery

import kombu_solace


pytestmark = [pytest.mark.integration, pytest.mark.celery_integration]


def _enabled() -> bool:
    return os.environ.get("SOLACE_RUN_CELERY_INTERRUPT") == "1"


def _broker_url() -> str:
    host = os.environ.get("SOLACE_HOST", "localhost")
    port = int(os.environ.get("SOLACE_PORT", "55588"))
    user = os.environ.get("SOLACE_USERNAME", "sampleUser")
    password = os.environ.get("SOLACE_PASSWORD", "samplePassword")
    vpn = os.environ.get("SOLACE_VPN", "default")
    return f"solace://{user}:{password}@{host}:{port}/{vpn}"


def _broker_transport_options() -> dict:
    return {
        "environment": os.environ.get("SOLACE_ENVIRONMENT", "DEV1"),
        "namespace": os.environ.get("SOLACE_NAMESPACE", "kombu-solace-celery"),
        "application": os.environ.get("SOLACE_APPLICATION", "celery-interrupt"),
        "queue_name_prefix": os.environ.get("SOLACE_QUEUE_PREFIX", "it"),
        "topic_prefix": os.environ.get("SOLACE_TOPIC_PREFIX", "it/celery"),
        "publish_confirm_mode": "sync",
        "publish_ack_timeout_ms": 10000,
        "publisher_buffer_capacity": 100,
        "receive_timeout": 1.0,
    }


@pytest.mark.skipif(not _enabled(), reason="Solace Celery interruption test not enabled")
def test_celery_acks_late_task_redelivers_after_worker_process_exit(tmp_path):
    kombu_solace.register_transport()
    suffix = uuid.uuid4().hex
    queue_name = f"celery-interrupt-{suffix}"
    marker = tmp_path / "first-attempt.txt"
    success = tmp_path / "redelivered.txt"
    module_path = tmp_path / "celery_interrupt_app.py"
    module_path.write_text(
        textwrap.dedent(
            f"""
            import os
            from celery import Celery
            import kombu_solace

            kombu_solace.register_transport()
            app = Celery("celery_interrupt_{suffix}", broker={_broker_url()!r})
            app.conf.update(
                task_default_queue={queue_name!r},
                task_queues=None,
                broker_transport_options={_broker_transport_options()!r},
                worker_prefetch_multiplier=1,
                task_acks_late=True,
                worker_enable_remote_control=False,
                worker_send_task_events=False,
                task_send_sent_event=False,
                broker_pool_limit=0,
            )

            @app.task(name="interrupt.maybe_crash")
            def maybe_crash(marker_path, success_path):
                if not os.path.exists(marker_path):
                    with open(marker_path, "w", encoding="utf-8") as fh:
                        fh.write("first")
                    os._exit(9)
                with open(success_path, "w", encoding="utf-8") as fh:
                    fh.write("redelivered")
                return "redelivered"
            """
        ),
        encoding="utf-8",
    )
    publisher = Celery(
        f"celery_interrupt_publisher_{suffix}",
        broker=_broker_url(),
        backend="cache+memory://",
    )
    publisher.conf.update(
        task_default_queue=queue_name,
        task_queues=None,
        broker_transport_options=_broker_transport_options(),
        broker_pool_limit=0,
    )

    first_worker = _start_worker(tmp_path, queue_name, suffix)
    try:
        publisher.send_task(
            "interrupt.maybe_crash",
            args=(str(marker), str(success)),
            queue=queue_name,
        )
        _wait_for(lambda: marker.exists(), timeout=30, reason="first task attempt")
        first_worker.wait(timeout=30)
        assert first_worker.returncode != 0
    finally:
        _terminate(first_worker)

    second_worker = _start_worker(tmp_path, queue_name, suffix)
    try:
        _wait_for(lambda: success.exists(), timeout=60, reason="redelivered task")
    finally:
        _terminate(second_worker)

    assert success.read_text(encoding="utf-8") == "redelivered"


def _start_worker(tmp_path, queue_name: str, suffix: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), os.getcwd(), env.get("PYTHONPATH", "")]
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "celery_interrupt_app",
            "worker",
            "-P",
            "solo",
            "-Q",
            queue_name,
            "-n",
            f"interrupt-{suffix}@%h",
            "--without-heartbeat",
            "--without-gossip",
            "--without-mingle",
            "--loglevel=ERROR",
        ],
        cwd=os.getcwd(),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _wait_for(predicate, *, timeout: float, reason: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.25)
    raise AssertionError(f"timed out waiting for {reason}")


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
