"""The generic dispatcher stores every row with event_type='unknown' ('adapter normalizes
this') but the adapter's normalization never reached the row. With `adapter=` passed,
rows are typed at storage time; without it, behaviour is unchanged."""
import json
from types import SimpleNamespace

import pytest

from django_bapp_connectors.services.webhook import WebhookService

from tests.testapp.models import Connection, WebhookEvent

BODY = json.dumps({"id": 15296, "name": "Cuier"}).encode()
HEADERS = {"X-Wc-Webhook-Topic": "order.created", "X-Wc-Webhook-Delivery-Id": "abc123"}


class FakeParsingAdapter:
    def parse_webhook(self, headers, body):
        return SimpleNamespace(
            event_type=SimpleNamespace(value="order.created"),
            provider_event_type="order.created",
            idempotency_key="woo-abc123",
            payload=json.loads(body),
        )


class ExplodingAdapter:
    def parse_webhook(self, headers, body):
        raise RuntimeError("bad payload")


@pytest.fixture
def connection(db):
    return Connection.objects.create(provider_family="shop", provider_name="woocommerce", display_name="Shop")


def _receive(adapter=None, body=BODY, connection=None):
    service = WebhookService(webhook_event_model=WebhookEvent)
    return service.receive(provider="woocommerce", headers=dict(HEADERS), body=body, connection=connection, adapter=adapter)


def test_adapter_types_the_stored_row(connection):
    event = _receive(adapter=FakeParsingAdapter(), connection=connection)
    assert event.event_type == "order.created"
    assert event.idempotency_key == "woo-abc123"
    row = WebhookEvent.objects.get(pk=event.pk)
    assert row.event_type == "order.created"


def test_adapter_key_drives_duplicate_detection(connection):
    _receive(adapter=FakeParsingAdapter(), connection=connection)
    second = _receive(adapter=FakeParsingAdapter(), body=BODY + b" ", connection=connection)  # alt body generic, aceeasi cheie adapter
    assert second.status == "duplicate"
    assert WebhookEvent.objects.count() == 1


def test_without_adapter_behaviour_is_unchanged(connection):
    event = _receive(connection=connection)
    assert event.event_type == "unknown"
    assert event.idempotency_key.startswith("woocommerce:")


def test_adapter_parse_failure_falls_back_to_generic(connection):
    event = _receive(adapter=ExplodingAdapter(), connection=connection)
    assert event.event_type == "unknown"
    assert WebhookEvent.objects.count() == 1


def test_adapter_without_parse_webhook_is_ignored(connection):
    event = _receive(adapter=object(), connection=connection)
    assert event.event_type == "unknown"


def test_process_webhook_backfills_unknown_event_type(connection, monkeypatch):
    pytest.importorskip("celery")
    from django_bapp_connectors.tasks import process_webhook

    row = WebhookEvent.objects.create(
        provider="woocommerce", event_type="unknown", idempotency_key="k1",
        payload={"id": 15296}, headers=dict(HEADERS), connection=connection,
    )
    # process_webhook reloads the event (and its connection) from the DB, so an
    # instance-level attribute would be invisible — patch the class.
    monkeypatch.setattr(Connection, "get_adapter", lambda self: FakeParsingAdapter(), raising=False)
    process_webhook(webhook_event_id=row.pk, app_label="testapp", model_name="webhookevent")
    row.refresh_from_db()
    assert row.event_type == "order.created"
    assert row.status == "processed"
