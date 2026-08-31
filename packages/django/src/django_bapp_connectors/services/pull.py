"""
PullService — provider → local product pull with echo suppression.

The service walks `adapter.get_products(...)` pages, suppresses echoes of our own pushes
(remote modified marker == link.remote_hash), and delegates every real change to the
consumer's `on_item` callback, which applies it locally and returns a PullDecision.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from django.utils import timezone

from django_bapp_connectors.services.push import PushService

logger = logging.getLogger(__name__)

REMOTE_MODIFIED_KEY = "date_modified_gmt"


@dataclass
class PullDecision:
    local_id: str = ""
    content_hash: str = ""
    applied: bool = True
    conflict: bool = False
    skipped: bool = False
    error: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class PullReport:
    created: int = 0
    updated: int = 0
    echoes: int = 0
    conflicts: int = 0
    skipped: int = 0
    failed: int = 0
    pages: int = 0
    errors: list[dict] = field(default_factory=list)
    locked: bool = False

    def summary(self) -> str:
        if self.locked:
            return "sync already running"
        return (f"{self.created} created, {self.updated} updated, {self.echoes} echoes, "
                f"{self.conflicts} conflicts, {self.skipped} skipped, {self.failed} failed")


class PullService:
    @staticmethod
    def _remote_modified(product) -> str:
        return str((getattr(product, "extra", None) or {}).get(REMOTE_MODIFIED_KEY, "") or "")

    @classmethod
    def pull(
        cls,
        connection,
        sync_state,
        resource_type: str,
        on_item: Callable,
        *,
        link_model,
        adapter=None,
        full: bool = False,
        max_pages: int | None = None,
    ) -> PullReport:
        from bapp_connectors.core.errors import AuthenticationError

        report = PullReport()
        if not PushService.acquire_lock(sync_state):
            report.locked = True
            return report
        started_at = timezone.now()
        try:
            if adapter is None:
                from django_bapp_connectors.services.connection import ConnectionService
                adapter = ConnectionService.get_adapter(connection)

            since = None if full else sync_state.last_sync_at
            cursor = sync_state.cursor or None
            supports_since = bool(getattr(adapter, "supports_modified_since", False))
            while True:
                page = adapter.get_products(cursor=cursor, since=since) if supports_since else adapter.get_products(cursor=cursor)
                report.pages += 1
                remote_ids = [p.product_id for p in page.items]
                links = {
                    link.remote_id: link
                    for link in link_model.objects.filter(connection=connection, resource_type=resource_type, remote_id__in=remote_ids)
                }
                for product in page.items:
                    link = links.get(product.product_id)
                    remote_modified = cls._remote_modified(product)
                    if link is not None and remote_modified and link.remote_hash == remote_modified:
                        report.echoes += 1
                        continue
                    try:
                        decision = on_item(product, link)
                    except Exception as e:  # noqa: BLE001 — one bad item must not stop the page
                        logger.exception("pull on_item failed for remote %s", product.product_id)
                        decision = PullDecision(error=str(e))
                    cls._apply_decision(connection, resource_type, link_model, product, link, decision, remote_modified, report)
                if not page.has_more:
                    cursor = None
                    break
                cursor = page.cursor
                if max_pages is not None and report.pages >= max_pages:
                    break

            if cursor:
                # partial run: keep resume point, do not move last_sync_at
                sync_state.mark_completed(cursor=cursor, last_sync_at=sync_state.last_sync_at)
            else:
                sync_state.cursor = ""
                sync_state.save(update_fields=["cursor", "updated_at"])
                sync_state.mark_completed(last_sync_at=started_at)
        except AuthenticationError as e:
            connection.record_auth_failure(str(e))
            sync_state.mark_failed(str(e))
            report.errors.append({"remote_id": "", "error": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.exception("Pull failed for %s on connection %s", resource_type, connection.pk)
            sync_state.mark_failed(str(e))
            report.errors.append({"remote_id": "", "error": str(e)})
        return report

    @staticmethod
    def _apply_decision(connection, resource_type, link_model, product, link, decision: PullDecision, remote_modified: str, report: PullReport) -> None:
        if decision.conflict:
            # a conflict carries its reason in `error`; check it first so it is not
            # counted as a failure
            report.conflicts += 1
            if link is not None:
                link.mark_conflict(decision.error or "conflict")
            return
        if decision.error:
            report.failed += 1
            report.errors.append({"remote_id": product.product_id, "error": decision.error})
            if link is None:
                link = link_model.objects.create(
                    connection=connection, resource_type=resource_type,
                    local_id=decision.local_id or f"remote:{product.product_id}", remote_id=product.product_id,
                )
            link.mark_error(decision.error, extra=decision.extra)
            return
        if decision.skipped or not decision.applied:
            report.skipped += 1
            return
        is_new = link is None
        if link is None:
            link, _ = link_model.objects.get_or_create(
                connection=connection, resource_type=resource_type, local_id=decision.local_id,
                defaults={"remote_id": product.product_id},
            )
        link.mark_linked(
            remote_id=product.product_id, content_hash=decision.content_hash,
            remote_hash=remote_modified, pulled=True, extra=decision.extra,
        )
        if is_new:
            report.created += 1
        else:
            report.updated += 1
