from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from bapp_connectors.core.capabilities import BulkUpsertCapability, ProductCreationCapability, ProductFullUpdateCapability
from bapp_connectors.core.dto import BulkItemResult, BulkUpsertResult, ConnectionTestResult, PaginatedResult, Product
from bapp_connectors.core.ports import ShopPort
from django.utils import timezone

from django_bapp_connectors.services.push import PushItem, PushService

from tests.testapp.models import Connection, SyncLink, SyncState


class FakeBulkShop(ShopPort, ProductCreationCapability, ProductFullUpdateCapability, BulkUpsertCapability):
    manifest = None  # type: ignore
    max_batch_size = 100

    def __init__(self, fail_skus=()):
        self.batches = []
        self.fail_skus = set(fail_skus)

    def validate_credentials(self): return True
    def test_connection(self): return ConnectionTestResult(success=True)
    def get_orders(self, since=None, cursor=None): return PaginatedResult(items=[])
    def get_order(self, order_id): return {}
    def get_products(self, cursor=None, since=None): return PaginatedResult(items=[])
    def update_product_stock(self, product_id, quantity): pass
    def update_product_price(self, product_id, price, currency): pass
    def update_order_status(self, order_id, status): raise NotImplementedError
    def create_product(self, product): return product
    def delete_product(self, product_id): pass
    def update_product(self, update): pass

    def bulk_upsert_products(self, creates, updates):
        self.batches.append((creates, updates))
        created = [
            BulkItemResult(index=i, error="SKU exists", error_code="product_invalid_sku", extra={"resource_id": 900})
            if p.sku in self.fail_skus else
            BulkItemResult(index=i, remote_id=f"w{p.product_id}", extra={"date_modified_gmt": "2026-08-31T09:00:00"})
            for i, p in enumerate(creates)
        ]
        updated = [BulkItemResult(index=i, remote_id=u.product_id, extra={"date_modified_gmt": "2026-08-31T09:00:01"}) for i, u in enumerate(updates)]
        return BulkUpsertResult(created=created, updated=updated)


@pytest.fixture
def connection(db):
    return Connection.objects.create(provider_family="shop", provider_name="woocommerce", display_name="Shop", is_enabled=True, is_connected=True)


@pytest.fixture
def sync_state(connection):
    return SyncState.objects.create(connection=connection, resource_type="products_push")


def _item(local_id, h="h1", sku=None):
    return PushItem(local_id=local_id, dto=Product(product_id=local_id, sku=sku or f"S{local_id}", name=f"P{local_id}", price=Decimal("1")), content_hash=h)


def test_creates_links_and_records_remote_ids(connection, sync_state):
    shop = FakeBulkShop()
    report = PushService.push(connection, sync_state, "product", [_item("1"), _item("2")], link_model=SyncLink, adapter=shop)
    assert report.created == 2 and report.failed == 0 and report.locked is False
    link = SyncLink.objects.get(connection=connection, resource_type="product", local_id="1")
    assert link.status == SyncLink.STATUS_LINKED and link.remote_id == "w1"
    assert link.content_hash == "h1" and link.remote_hash == "2026-08-31T09:00:00" and link.last_pushed_at
    sync_state.refresh_from_db()
    assert sync_state.status == "completed"


def test_unchanged_hash_is_skipped_without_any_adapter_call(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="1", remote_id="w1", content_hash="h1", status=SyncLink.STATUS_LINKED)
    shop = FakeBulkShop()
    report = PushService.push(connection, sync_state, "product", [_item("1", "h1")], link_model=SyncLink, adapter=shop)
    assert report.skipped_unchanged == 1 and shop.batches == []


def test_changed_hash_goes_out_as_update_with_remote_id(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="1", remote_id="w1", content_hash="old", status=SyncLink.STATUS_LINKED)
    shop = FakeBulkShop()
    report = PushService.push(connection, sync_state, "product", [_item("1", "new")], link_model=SyncLink, adapter=shop)
    creates, updates = shop.batches[0]
    assert creates == [] and updates[0].product_id == "w1"
    assert report.updated == 1
    assert SyncLink.objects.get(local_id="1").content_hash == "new"


def test_error_link_with_remote_id_is_retried_even_if_hash_equal(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="1", remote_id="w1", content_hash="h1", status=SyncLink.STATUS_ERROR)
    shop = FakeBulkShop()
    PushService.push(connection, sync_state, "product", [_item("1", "h1")], link_model=SyncLink, adapter=shop)
    assert len(shop.batches) == 1
    assert SyncLink.objects.get(local_id="1").status == SyncLink.STATUS_LINKED


def test_positional_error_marks_only_that_link(connection, sync_state):
    shop = FakeBulkShop(fail_skus={"S2"})
    report = PushService.push(connection, sync_state, "product", [_item("1"), _item("2"), _item("3")], link_model=SyncLink, adapter=shop)
    assert report.created == 2 and report.failed == 1
    bad = SyncLink.objects.get(local_id="2")
    assert bad.status == SyncLink.STATUS_ERROR and "SKU exists" in bad.last_error
    assert bad.extra["error_code"] == "product_invalid_sku" and bad.extra["resource_id"] == 900
    assert report.errors[0]["local_id"] == "2"


def test_lock_held_returns_locked_report(connection, sync_state):
    sync_state.mark_running()
    shop = FakeBulkShop()
    report = PushService.push(connection, sync_state, "product", [_item("1")], link_model=SyncLink, adapter=shop)
    assert report.locked is True and shop.batches == []


def test_stale_lock_is_taken_over(connection, sync_state):
    sync_state.mark_running()
    SyncState.objects.filter(pk=sync_state.pk).update(updated_at=timezone.now() - timedelta(minutes=PushService.LOCK_STALE_MINUTES + 1))
    sync_state.refresh_from_db()
    report = PushService.push(connection, sync_state, "product", [_item("1")], link_model=SyncLink, adapter=FakeBulkShop())
    assert report.locked is False and report.created == 1


def test_engine_level_batch_failure_marks_links_error_and_completes_state(connection, sync_state):
    class Boom(FakeBulkShop):
        def bulk_upsert_products(self, creates, updates):
            raise RuntimeError("502 Bad Gateway")

    report = PushService.push(connection, sync_state, "product", [_item("1")], link_model=SyncLink, adapter=Boom())
    assert report.failed == 1
    sync_state.refresh_from_db()
    assert sync_state.status == "completed"  # per-batch errors are absorbed by the engine; state completes
    assert SyncLink.objects.get(local_id="1").status == SyncLink.STATUS_ERROR


def test_uses_connection_adapter_when_not_injected(connection, sync_state):
    with patch("django_bapp_connectors.services.connection.ConnectionService.get_adapter", return_value=FakeBulkShop()) as get_adapter:
        PushService.push(connection, sync_state, "product", [_item("1")], link_model=SyncLink)
    get_adapter.assert_called_once()
