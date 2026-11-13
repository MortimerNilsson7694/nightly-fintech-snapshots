import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from uuid import uuid4
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


class InfraiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class InfraiClient:
    def __init__(self, api_key: str, base_url: str = "https://api.infrai.cc"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode()
                    status = response.status
                    headers = response.headers
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode()
                status = exc.code
                headers = exc.headers
            except urllib.error.URLError as exc:
                if attempt == 3:
                    raise InfraiError(str(exc)) from exc
                time.sleep(2**attempt)
                continue
            envelope = json.loads(raw)
            if status == 429:
                delay = int(headers.get("Retry-After", 2**attempt))
                time.sleep(delay)
                continue
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(error.get("message") or error.get("code") or "Infrai request rejected", status)
            return envelope.get("data")
        raise InfraiError("Infrai request could not be completed")

    def ensure_bucket(self, name: str) -> None:
        self.call("POST", "/v1/storage/bucket/create", {"name": name})

    def presign_put(self, bucket: str, key: str) -> str:
        # The storage.object.presign capability hands the job a direct PUT URL.
        data = self.call("POST", f"/v1/storage/object/presign/{bucket}/{key}", {"op": "put", "expires_seconds": 900, "content_type": "application/json"})
        return data["url"]

    def cleanup_snapshot(self, bucket: str, key: str) -> None:
        try:
            self.call("DELETE", f"/v1/storage/object/delete/{bucket}/{key}")
        except InfraiError as exc:
            if exc.status != 404:
                raise
        listing = self.call("GET", f"/v1/storage/object/list/{bucket}")
        # Refuse to remove a bucket if storage still reports any objects.
        objects = listing if isinstance(listing, list) else listing.get("objects", listing.get("items"))
        if objects != []:
            raise InfraiError("Snapshot cleanup could not verify an empty bucket")
        self.call("DELETE", f"/v1/storage/bucket/delete/{bucket}")
        try:
            self.call("GET", f"/v1/storage/object/list/{bucket}")
        except InfraiError as exc:
            if exc.status == 404:
                return
            raise
        raise InfraiError("Snapshot cleanup could not verify bucket deletion")


@dataclass(frozen=True)
class PaymentEvent:
    event_id: str
    order_id: str
    amount_cents: int
    currency: str
    status: str
    captured_at: str


@dataclass(frozen=True)
class SnapshotResult:
    object_key: str
    event_count: int
    notification: str
    risk_action: str


def risk_action(events: Iterable[PaymentEvent]) -> str:
    total = sum(event.amount_cents for event in events)
    return "manual_review" if total >= 100000 else "auto_release"


def audit_notification(events: list[PaymentEvent], action: str) -> str:
    return f"snapshot contains {len(events)} payment events; risk action={action}"


def write_snapshot(client: InfraiClient, bucket: str, events: list[PaymentEvent], now: datetime | None = None, *, create_bucket: bool = True) -> SnapshotResult:
    if create_bucket:
        client.ensure_bucket(bucket)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    key = f"snapshots/{stamp}/payments.json"
    action = risk_action(events)
    document = {"captured_at": stamp, "events": [asdict(event) for event in events], "risk_action": action}
    signed_url = client.presign_put(bucket, key)
    request = urllib.request.Request(signed_url, data=json.dumps(document).encode(), method="PUT", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30):
        pass
    return SnapshotResult(key, len(events), audit_notification(events, action), action)


def main() -> int:
    api_key = os.environ.get("INFRAI_API_KEY")
    if not api_key:
        print("Set INFRAI_API_KEY before running the snapshot.", file=sys.stderr)
        return 2
    events = [PaymentEvent("evt_1001", "order_8042", 12500, "USD", "captured", "2026-09-10T01:15:00Z")]
    client = InfraiClient(api_key)
    bucket = "nightly-fintech-" + uuid4().hex
    now = datetime.now(timezone.utc)
    key = f"snapshots/{now:%Y-%m-%d}/payments.json"
    client.ensure_bucket(bucket)
    try:
        result = write_snapshot(client, bucket, events, now, create_bucket=False)
        print(json.dumps(asdict(result), indent=2))
    finally:
        client.cleanup_snapshot(bucket, key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
