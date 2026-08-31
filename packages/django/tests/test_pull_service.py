from datetime import UTC, datetime

import pytest
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult, Product
from bapp_connectors.core.ports import ShopPort

from django_bapp_connectors.services.pull import PullDecision, PullService

from tests.testapp.models import Connection, SyncLink, SyncState


class FakePullShop(ShopPort):
    manifest = None  # type: ignore
    supports_modified_since = True

    def __init__(self, pages):
        self.pages = pages          # list[list[Product]]
        self.calls = []

    def validate_credentials(self): return True
    def test_connection(self): return ConnectionTestResult(success=True)
    def get_orders(self, since=None, cursor=None): return PaginatedResult(items=[])
    def get_order(self, order_id): return {}
    def update_product_stock(self, product_id, quantity): pass
    def update_product_price(self, product_id, price, currency): pass
    def update_order_status(self, order_id, status): raise NotImplementedError

    def get_products(self, cursor=None, since=None):
        self.calls.append({"cursor": cursor, "since": since})
        page = int(cursor) if cursor else 1
        items = self.pages[page - 1] if page - 1 < len(self.pages) else []
        return PaginatedResult(items=items, cursor=str(page + 1), has_more=page < len(self.pages))


def _remote(pid, modified="2026-08-31T08:00:00", sku=None):
    return Product(product_id=pid, sku=sku or f"S{pid}", name=f"R{pid}", extra={"date_modified_gmt": modified})


@pytest.fixture
def connection(db):
    return Connection.objects.create(provider_family="shop", provider_name="woocommerce", display_name="Shop", is_enabled=True, is_connected=True)


@pytest.fixture
def sync_state(connection):
    return SyncState.objects.create(connection=connection, resource_type="products_pull")


def test_new_remote_item_creates_link_from_decision(connection, sync_state):
    shop = FakePullShop([[_remote("100")]])
    seen = []

    def on_item(product, link):
        seen.append((product.product_id, link))
        return PullDecision(local_id="7", content_hash="h7")

    report = PullService.pull(connection, sync_state, "product", on_item, link_model=SyncLink, adapter=shop)
    assert seen == [("100", None)]
    assert report.created == 1
    link = SyncLink.objects.get(connection=connection, resource_type="product", local_id="7")
    assert link.remote_id == "100" and link.remote_hash == "2026-08-31T08:00:00" and link.content_hash == "h7" and link.last_pulled_at


def test_echo_of_our_own_push_is_skipped(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="7", remote_id="100", remote_hash="2026-08-31T08:00:00", status=SyncLink.STATUS_LINKED)
    shop = FakePullShop([[_remote("100", "2026-08-31T08:00:00")]])
    calls = []
    report = PullService.pull(connection, sync_state, "product", lambda p, l: calls.append(p) or PullDecision(local_id="7"), link_model=SyncLink, adapter=shop)
    assert report.echoes == 1 and calls == []


def test_remote_change_updates_existing_link(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="7", remote_id="100", remote_hash="2026-08-30T00:00:00", status=SyncLink.STATUS_LINKED)
    shop = FakePullShop([[_remote("100", "2026-08-31T08:00:00")]])
    report = PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(local_id=l.local_id, content_hash="h-new"), link_model=SyncLink, adapter=shop)
    assert report.updated == 1
    link = SyncLink.objects.get(local_id="7")
    assert link.remote_hash == "2026-08-31T08:00:00" and link.content_hash == "h-new"


def test_conflict_decision_marks_link_and_does_not_advance_hashes(connection, sync_state):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="7", remote_id="100", remote_hash="old", content_hash="local", status=SyncLink.STATUS_LINKED)
    shop = FakePullShop([[_remote("100")]])
    report = PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(local_id="7", conflict=True, error="modified locally"), link_model=SyncLink, adapter=shop)
    assert report.conflicts == 1
    link = SyncLink.objects.get(local_id="7")
    assert link.status == SyncLink.STATUS_CONFLICT and link.remote_hash == "old" and link.content_hash == "local"


def test_error_decision_on_unknown_remote_creates_error_link_keyed_by_remote(connection, sync_state):
    shop = FakePullShop([[_remote("100")]])
    report = PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(error="no sku"), link_model=SyncLink, adapter=shop)
    assert report.failed == 1
    link = SyncLink.objects.get(connection=connection, resource_type="product", remote_id="100")
    assert link.status == SyncLink.STATUS_ERROR and link.local_id == "remote:100"


def test_incremental_passes_last_sync_at_as_since_and_full_passes_none(connection, sync_state):
    sync_state.mark_completed(last_sync_at=datetime(2026, 8, 30, 6, 0, tzinfo=UTC))
    shop = FakePullShop([[]])
    PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(skipped=True), link_model=SyncLink, adapter=shop)
    assert shop.calls[0]["since"] == datetime(2026, 8, 30, 6, 0, tzinfo=UTC)
    shop2 = FakePullShop([[]])
    PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(skipped=True), link_model=SyncLink, adapter=shop2, full=True)
    assert shop2.calls[0]["since"] is None


def test_walks_all_pages_and_respects_max_pages(connection, sync_state):
    shop = FakePullShop([[_remote("1")], [_remote("2")], [_remote("3")]])
    report = PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(local_id=p.product_id), link_model=SyncLink, adapter=shop, max_pages=2)
    assert report.pages == 2 and report.created == 2
    sync_state.refresh_from_db()
    assert sync_state.cursor == "3"          # resume point
    assert sync_state.status == "completed"


def test_completed_run_clears_cursor_and_sets_last_sync_at(connection, sync_state):
    shop = FakePullShop([[_remote("1")]])
    PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(local_id="1"), link_model=SyncLink, adapter=shop)
    sync_state.refresh_from_db()
    assert sync_state.cursor == "" and sync_state.last_sync_at is not None


def test_locked_state_returns_locked_report(connection, sync_state):
    sync_state.mark_running()
    report = PullService.pull(connection, sync_state, "product", lambda p, l: PullDecision(), link_model=SyncLink, adapter=FakePullShop([[_remote("1")]]))
    assert report.locked is True
