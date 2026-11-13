from datetime import datetime, timezone

from src.fintech_snapshot import PaymentEvent, audit_notification, risk_action


def test_high_value_checkout_requires_review():
    events = [PaymentEvent("evt", "order", 100000, "USD", "captured", "2026-09-10T00:00:00Z")]
    assert risk_action(events) == "manual_review"
    assert "manual_review" in audit_notification(events, risk_action(events))


def test_small_checkout_is_released():
    events = [PaymentEvent("evt", "order", 4999, "USD", "captured", "2026-09-10T00:00:00Z")]
    assert risk_action(events) == "auto_release"


def test_cleanup_verifies_object_and_bucket_deletion(monkeypatch):
    from src.fintech_snapshot import InfraiClient, InfraiError

    client = InfraiClient('test')
    calls = []
    def call(method, path, body=None):
        calls.append((method, path))
        if method == 'GET':
            if len(calls) == 4:
                raise InfraiError('Bucket not found', 404)
            return {'objects': []}
    monkeypatch.setattr(client, 'call', call)
    client.cleanup_snapshot('demo', 'snapshot.json')
    assert calls == [
        ('DELETE', '/v1/storage/object/delete/demo/snapshot.json'),
        ('GET', '/v1/storage/object/list/demo'),
        ('DELETE', '/v1/storage/bucket/delete/demo'),
        ('GET', '/v1/storage/object/list/demo'),
    ]


def test_demo_cleans_up_after_upload_failure(monkeypatch):
    import pytest
    from src import fintech_snapshot as snapshot

    cleaned = []
    monkeypatch.setenv('INFRAI_API_KEY', 'test')
    monkeypatch.setattr(snapshot.InfraiClient, 'ensure_bucket', lambda *args: None)
    def fail(*args, **kwargs):
        raise RuntimeError('upload failed')
    monkeypatch.setattr(snapshot, 'write_snapshot', fail)
    monkeypatch.setattr(snapshot.InfraiClient, 'cleanup_snapshot', lambda self, bucket, key: cleaned.append((bucket, key)))
    with pytest.raises(RuntimeError, match='upload failed'):
        snapshot.main()
    assert len(cleaned) == 1
    assert cleaned[0][0].startswith('nightly-fintech-')
    assert cleaned[0][1].endswith('/payments.json')
