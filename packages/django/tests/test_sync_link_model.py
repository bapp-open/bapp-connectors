import pytest
from django.db import IntegrityError

from tests.testapp.models import Connection, SyncLink


@pytest.fixture
def connection(db):
    return Connection.objects.create(provider_family="shop", provider_name="woocommerce", display_name="Shop", is_enabled=True, is_connected=True)


def test_new_link_is_pending(connection):
    link = SyncLink.objects.create(connection=connection, resource_type="product", local_id="10")
    assert link.status == SyncLink.STATUS_PENDING and link.remote_id == ""


def test_mark_linked_sets_hashes_and_timestamps(connection):
    link = SyncLink.objects.create(connection=connection, resource_type="product", local_id="10")
    link.mark_linked(remote_id="55", content_hash="abc", remote_hash="2026-08-31T00:00:00", pushed=True, extra={"sku": "X"})
    link.refresh_from_db()
    assert link.status == SyncLink.STATUS_LINKED
    assert link.remote_id == "55" and link.content_hash == "abc" and link.remote_hash == "2026-08-31T00:00:00"
    assert link.last_pushed_at is not None and link.last_pulled_at is None
    assert link.last_error == "" and link.extra["sku"] == "X"


def test_mark_error_keeps_remote_id_and_records_message(connection):
    link = SyncLink.objects.create(connection=connection, resource_type="product", local_id="10", remote_id="55")
    link.mark_error("boom" * 1000, extra={"resource_id": 77})
    link.refresh_from_db()
    assert link.status == SyncLink.STATUS_ERROR and link.remote_id == "55"
    assert len(link.last_error) <= 2000 and link.extra["resource_id"] == 77


def test_mark_skipped_and_conflict(connection):
    link = SyncLink.objects.create(connection=connection, resource_type="product", local_id="10")
    link.mark_skipped("no_sku")
    assert link.status == SyncLink.STATUS_SKIPPED and link.extra["skip_reason"] == "no_sku"
    link.mark_conflict("modified locally")
    assert link.status == SyncLink.STATUS_CONFLICT and link.last_error == "modified locally"


def test_local_id_unique_per_connection_and_resource(connection):
    SyncLink.objects.create(connection=connection, resource_type="product", local_id="10")
    with pytest.raises(IntegrityError):
        SyncLink.objects.create(connection=connection, resource_type="product", local_id="10")
