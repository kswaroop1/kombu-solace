"""Optional SEMP-backed management operations."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .errors import ManagementUnavailable


@dataclass(frozen=True)
class SempV2ManagementAdapter:
    """Minimal SEMP v2 management adapter.

    The adapter is optional. Transport operations fall back to messaging API
    strategies when this adapter is absent or raises `ManagementUnavailable`.
    """

    base_url: str
    vpn_name: str
    username: str | None = None
    password: str | None = None
    timeout: float = 5.0
    verify_tls: bool = True

    def queue_size(self, queue_name: str) -> int:
        return len(self._list_action_messages(queue_name))

    def delete_queue(self, queue_name: str) -> None:
        path = f"/SEMP/v2/config/msgVpns/{_q(self.vpn_name)}/queues/{_q(queue_name)}"
        self._request_json("DELETE", path)

    def purge_queue(self, queue_name: str) -> int:
        """Delete queued messages through SEMP v2 action endpoints.

        Newer broker versions may expose bulk delete actions. This conservative
        implementation lists message ids and deletes them one by one so it can
        gracefully fail and let the transport fall back to receiver-drain purge.
        """

        deleted = 0
        while True:
            messages = self._list_action_messages(queue_name)
            if not messages:
                return deleted
            for message in messages:
                msg_id = _extract_message_id(message)
                if msg_id is None:
                    raise ManagementUnavailable("SEMP message id was not present")
                self._delete_action_message(queue_name, msg_id)
                deleted += 1

    def _list_action_messages(self, queue_name: str) -> list[dict]:
        path = (
            f"/SEMP/v2/action/msgVpns/{_q(self.vpn_name)}/queues/"
            f"{_q(queue_name)}/msgs"
        )
        response = self._request_json("GET", path)
        data = response.get("data", [])
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        raise ManagementUnavailable("unexpected SEMP message list response")

    def _delete_action_message(self, queue_name: str, msg_id: str) -> None:
        path = (
            f"/SEMP/v2/action/msgVpns/{_q(self.vpn_name)}/queues/"
            f"{_q(queue_name)}/msgs/{_q(str(msg_id))}/delete"
        )
        self._request_json("PUT", path, body={})

    def _request_json(self, method: str, path: str, body: dict | None = None) -> dict:
        url = self.base_url.rstrip("/") + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        if self.username is not None or self.password is not None:
            import base64

            token = base64.b64encode(
                f"{self.username or ''}:{self.password or ''}".encode("utf-8")
            ).decode("ascii")
            request.add_header("Authorization", f"Basic {token}")
        try:
            context = None if self.verify_tls else ssl._create_unverified_context()
            with urlopen(request, timeout=self.timeout, context=context) as response:
                raw = response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise ManagementUnavailable(str(exc)) from exc
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ManagementUnavailable("SEMP response was not JSON") from exc


def _q(value: str) -> str:
    return quote(value, safe="")


def _extract_message_id(message: dict) -> str | None:
    for key in ("msgId", "msg-id", "messageId", "message-id", "id"):
        value = message.get(key)
        if value is not None:
            return str(value)
    return None
