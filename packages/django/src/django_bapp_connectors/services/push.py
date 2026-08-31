"""
PushService — local → provider product push with hash-based change detection.

Provider- and domain-agnostic: the caller builds `PushItem`s (a framework Product DTO
plus a content hash) and passes the concrete SyncLink model. SyncState doubles as the
per-connection lock so two workers never push the same resource concurrently.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class PushItem:
    local_id: str
    dto: object                # bapp_connectors.core.dto.Product, with product_id == local_id
    content_hash: str
    extra: dict = field(default_factory=dict)


@dataclass
class PushReport:
    created: int = 0
    updated: int = 0
    skipped_unchanged: int = 0
    failed: int = 0
    processed: int = 0
    errors: list[dict] = field(default_factory=list)
    locked: bool = False

    def summary(self) -> str:
        if self.locked:
            return "sync already running"
        return (f"{self.created} created, {self.updated} updated, "
                f"{self.skipped_unchanged} unchanged, {self.failed} failed")


class PushService:
    LOCK_STALE_MINUTES = 30

    @classmethod
    def acquire_lock(cls, sync_state) -> bool:
        """Take the SyncState lock. A 'running' state older than LOCK_STALE_MINUTES is
        considered dead (worker killed) and is taken over with a warning."""
        if sync_state.status == "running":
            age = timezone.now() - (sync_state.updated_at or timezone.now())
            if age < timedelta(minutes=cls.LOCK_STALE_MINUTES):
                return False
            logger.warning("Taking over stale sync lock %s (age %s)", sync_state.pk, age)
        sync_state.mark_running()
        return True

    @classmethod
    def push(
        cls,
        connection,
        sync_state,
        resource_type: str,
        items: Iterable[PushItem],
        *,
        link_model,
        batch_size: int = 20,
        pause_seconds: float = 0.0,
        adapter=None,
        engine=None,
        cursor: str = "",
        release_lock: bool = True,
    ) -> PushReport:
        from bapp_connectors.core.errors import AuthenticationError
        from bapp_connectors.core.sync import ProductSyncEngine

        report = PushReport()
        if not cls.acquire_lock(sync_state):
            report.locked = True
            return report
        try:
            if adapter is None:
                from django_bapp_connectors.services.connection import ConnectionService
                adapter = ConnectionService.get_adapter(connection)
            engine = engine or ProductSyncEngine()

            items = list(items)
            report.processed = len(items)
            links = {
                link.local_id: link
                for link in link_model.objects.filter(
                    connection=connection, resource_type=resource_type,
                    local_id__in=[i.local_id for i in items],
                )
            }
            to_push: list[PushItem] = []
            for item in items:
                link = links.get(item.local_id)
                if link is not None and link.status == link.STATUS_LINKED and link.remote_id and link.content_hash == item.content_hash:
                    report.skipped_unchanged += 1
                    continue
                if link is None:
                    link = link_model.objects.create(connection=connection, resource_type=resource_type, local_id=item.local_id)
                    links[item.local_id] = link
                to_push.append(item)

            if to_push:
                def match_fn(dto):
                    link = links.get(dto.product_id)
                    return (link.remote_id or None) if link else None

                result = engine.push_products(
                    adapter, [i.dto for i in to_push], match_fn=match_fn,
                    batch_size=batch_size, pause_seconds=pause_seconds,
                )
                errors_by_id = {e.product_id: e for e in result.errors}
                for item in to_push:
                    link = links[item.local_id]
                    err = errors_by_id.get(item.local_id)
                    if err is not None:
                        report.failed += 1
                        extra = dict(err.extra or {})
                        if err.code:
                            extra["error_code"] = err.code
                        link.mark_error(err.error, extra=extra)
                        report.errors.append({"local_id": item.local_id, "error": err.error, "code": err.code, "extra": extra})
                        continue
                    remote_id = result.remote_ids.get(item.local_id) or link.remote_id
                    was_new = not link.remote_id
                    link.mark_linked(
                        remote_id=remote_id,
                        content_hash=item.content_hash,
                        remote_hash=(result.remote_meta.get(item.local_id) or {}).get("date_modified_gmt", ""),
                        pushed=True,
                        extra=item.extra,
                    )
                    if was_new:
                        report.created += 1
                    else:
                        report.updated += 1
            if release_lock:
                sync_state.mark_completed(cursor=cursor)
        except AuthenticationError as e:
            connection.record_auth_failure(str(e))
            sync_state.mark_failed(str(e))
            report.errors.append({"local_id": "", "error": str(e), "code": "auth", "extra": {}})
        except Exception as e:  # noqa: BLE001 — never leave the lock held
            logger.exception("Push failed for %s on connection %s", resource_type, connection.pk)
            sync_state.mark_failed(str(e))
            report.errors.append({"local_id": "", "error": str(e), "code": "", "extra": {}})
        return report
