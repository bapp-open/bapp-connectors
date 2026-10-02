"""Adapterul Google Play — AppStorePort + FinancialCapability + WebhookCapability."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.dto import (
    AppStoreApp,
    AppStoreRefund,
    AppStoreReview,
    AppStoreSale,
    ConnectionTestResult,
    FinancialTransaction,
    PaginatedResult,
    Subscription,
    WebhookEvent,
)
from bapp_connectors.core.errors import PermanentProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.reports import csv_rows, decode_text, monthly_page, unzip_csv_rows
from bapp_connectors.providers.appstore.google_play.auth import (
    SCOPE_ANDROID_PUBLISHER,
    SCOPE_STORAGE_RO,
    GoogleServiceAccountAuth,
    bucket_name_from_uri,
    parse_service_account,
)
from bapp_connectors.providers.appstore.google_play.client import GooglePlayApiClient
from bapp_connectors.providers.appstore.google_play.errors import GooglePlayWebhookError
from bapp_connectors.providers.appstore.google_play.manifest import manifest
from bapp_connectors.providers.appstore.google_play.mappers import (
    app_from_package,
    refund_from_voided,
    review_from_api,
    review_from_csv_row,
    sale_from_sales_row,
    subscription_from_v2,
    transactions_from_earnings_rows,
    webhook_event_from_pubsub,
)

#: numele fisierului din fiecare folder incepe cu acest prefix, urmat de stamp-ul YYYYMM
#: Google serveste ~30 de zile, dar respinge exact 30 ("Start time must be within [30] days of data")
VOIDED_LOOKBACK_DAYS = 29
_BASENAME_PREFIXES = {"earnings/": "earnings_", "sales/": "salesreport_"}


def _stamp_for(name: str, prefix: str) -> str | None:
    """Stamp-ul YYYYMM aflat imediat dupa prefixul cunoscut al fisierului, sau None.

    `earnings/` -> `earnings/earnings_YYYYMM...`, `sales/` -> `sales/salesreport_YYYYMM...`, iar un prefix
    complet (`reviews/reviews_{package}_`) e urmat direct de stamp. Pozitional, ca cifrele din numele
    pachetului sa nu poata fi luate drept luna.
    """
    full_prefix = prefix + _BASENAME_PREFIXES.get(prefix, "")
    if not name.startswith(full_prefix):
        return None
    stamp = name[len(full_prefix) : len(full_prefix) + 6]
    return stamp if len(stamp) == 6 and stamp.isdigit() else None


class GooglePlayAdapter(AppStorePort, FinancialCapability, WebhookCapability):
    manifest = manifest

    def __init__(self, credentials: dict, http_client: ResilientHttpClient | None = None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        self.config = config or {}
        self.service_account = parse_service_account(credentials.get("service_account_json") or "{}") if credentials.get("service_account_json") else {}
        self.bucket = bucket_name_from_uri(credentials.get("bucket_uri", ""))
        self.package_names = [p.strip() for p in (credentials.get("package_names") or "").split(",") if p.strip()]
        self.auth = GoogleServiceAccountAuth(self.service_account, [SCOPE_STORAGE_RO, SCOPE_ANDROID_PUBLISHER]) if self.service_account else None
        if http_client is None:
            http_client = ResilientHttpClient(base_url=self.manifest.base_url, auth=self.auth, provider_name="google_play")
        elif self.auth is not None:
            http_client.auth = self.auth
        self.http = http_client
        self._jwks_cache: dict = {}
        self.client = GooglePlayApiClient(http_client=http_client, bucket=self.bucket)

    # ── BasePort ──

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials) and bool(self.service_account)

    def test_connection(self) -> ConnectionTestResult:
        try:
            ok = self.client.test_auth()
            return ConnectionTestResult(success=ok, message="Connection successful" if ok else "Bucket inaccesibil")
        except Exception as exc:
            return ConnectionTestResult(success=False, message=str(exc))

    def _require_packages(self, what: str) -> list[str]:
        if not self.package_names:
            raise NotImplementedError(f"Google Play: {what} cere credentialul package_names")
        return self.package_names

    # ── rapoarte din bucket ──

    def _month_objects(self, prefix: str, year: int, month: int) -> list[str]:
        stamp = f"{year:04d}{month:02d}"
        all_names = [obj["name"] for obj in self.client.list_objects(prefix)]
        stamps = {name: _stamp_for(name, prefix) for name in all_names}
        if all_names and not any(stamps.values()):
            raise PermanentProviderError(
                f"Google Play: niciun obiect sub {prefix} nu are stamp YYYYMM recunoscut: {all_names[:3]}"
            )
        return [name for name in all_names if stamps[name] == stamp]

    def _month_rows(self, prefix: str, year: int, month: int) -> list[dict]:
        rows: list[dict] = []
        for name in self._month_objects(prefix, year, month):
            content = self.client.download_object(name)
            rows.extend(unzip_csv_rows(content) if name.lower().endswith(".zip") else csv_rows(decode_text(content)))
        return rows

    # ── AppStorePort ──

    def list_apps(self) -> list[AppStoreApp]:
        titles: dict[str, str] = {}
        today = date.today()
        last_month = today.replace(day=1) - timedelta(days=1)
        rows = self._month_rows("sales/", today.year, today.month) or self._month_rows("sales/", last_month.year, last_month.month)
        for row in rows:
            titles.setdefault(row.get("Package ID", ""), row.get("Product Title", ""))
        packages = self.package_names or [p for p in titles if p]
        return [app_from_package(p, titles.get(p, "")) for p in packages]

    def get_sales(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreSale]:
        (year, month), next_cursor = monthly_page(start, end, cursor)
        items = [sale_from_sales_row(row, year, month) for row in self._month_rows("sales/", year, month)]
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_refunds(self, start: date, end: date, cursor: str | None = None) -> PaginatedResult[AppStoreRefund]:
        packages = self._require_packages("cumparaturile anulate")
        index, token = (int(cursor.split(":", 1)[0]), cursor.split(":", 1)[1] or None) if cursor else (0, None)
        package = packages[index]
        now_ms = int(time.time() * 1000)
        # voidedpurchases respinge endTime >= acum ("End time must be < current time") si serveste doar ultimele 30 de zile
        end_ms = min(int(datetime.combine(end, datetime.max.time(), tzinfo=UTC).timestamp() * 1000), now_ms - 1000)
        start_ms = max(int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp() * 1000), now_ms - VOIDED_LOOKBACK_DAYS * 86400 * 1000)
        if start_ms >= end_ms:
            return PaginatedResult(items=[], has_more=False)
        page = self.client.list_voided_purchases(package, start_ms, end_ms, token=token)
        items = [refund_from_voided(v, package) for v in page.get("voidedPurchases", [])]
        next_token = (page.get("tokenPagination") or {}).get("nextPageToken")
        if next_token:
            next_cursor = f"{index}:{next_token}"
        elif index + 1 < len(packages):
            next_cursor = f"{index + 1}:"
        else:
            next_cursor = None
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def list_reviews(self, app_id: str, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[AppStoreReview]:
        """Istoricul din CSV-urile lunare + recenziile live din API (ultimele 7 zile) pe pagina lunii curente.

        Consumatorii fac upsert dupa `review_id`, deci o recenzie prezenta si intr-un CSV lunar si in API
        se reconciliaza dupa id.
        """
        since = since or datetime.now(UTC) - timedelta(days=92)
        if since.tzinfo is None:
            since = since.replace(tzinfo=UTC)
        start, end = since.date(), date.today()
        (year, month), next_cursor = monthly_page(start, end, cursor)
        by_id: dict[str, AppStoreReview] = {}
        for row in self._month_rows(f"reviews/reviews_{app_id}_", year, month):
            review = review_from_csv_row(row, app_id)
            by_id[review.review_id] = review
        if (year, month) == (date.today().year, date.today().month) and self.package_names:
            for data in self.client.list_reviews(app_id).get("reviews", []):
                review = review_from_api(data, app_id)
                by_id[review.review_id] = review  # API-ul e mai proaspat decat CSV-ul
        items = [r for r in by_id.values() if r.updated_at is None or r.updated_at >= since]
        items.sort(key=lambda r: r.created_at or datetime.min.replace(tzinfo=UTC), reverse=True)
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    def reply_to_review(self, app_id: str, review_id: str, text: str) -> AppStoreReview:
        self._require_packages("raspunsul la recenzii")
        result = self.client.reply_review(app_id, review_id, text).get("result") or {}
        return review_from_api({"reviewId": review_id, "comments": [{"developerComment": {"text": result.get("replyText", text), "lastModified": result.get("lastEdited")}}]}, app_id)

    def get_subscription(self, reference: str) -> Subscription:
        """`reference` = `<package_name>:<purchase_token>`; fara prefix se foloseste primul pachet configurat."""
        packages = self._require_packages("abonamentele")
        package, _, token = reference.partition(":") if ":" in reference else (packages[0], "", reference)
        return subscription_from_v2(self.client.get_subscription_v2(package, token), token)

    # ── FinancialCapability ──

    def get_financial_transactions(self, start_date: datetime, end_date: datetime, transaction_type: str | None = None, cursor: str | None = None) -> PaginatedResult[FinancialTransaction]:
        (year, month), next_cursor = monthly_page(start_date.date(), end_date.date(), cursor)
        items = transactions_from_earnings_rows(self._month_rows("earnings/", year, month), year, month)
        if transaction_type:
            items = [t for t in items if t.transaction_type == transaction_type]
        return PaginatedResult(items=items, cursor=next_cursor, has_more=next_cursor is not None)

    # ── WebhookCapability (Pub/Sub push) — completat in Task 10 ──

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        """Fara `pubsub_audience` acceptam push-ul (verificarea OIDC e optionala la Pub/Sub).

        Cu `pubsub_audience` dar fara `pubsub_service_account_email` respingem tot: configurare incompleta = fail closed.
        """
        from bapp_connectors.providers.appstore.google_play.oidc import (
            UnknownKeyIdError,
            fetch_google_jwks,
            verify_google_id_token,
        )

        audience = secret or self.credentials.get("pubsub_audience") or ""
        if not audience:
            return True
        service_account_email = (self.credentials.get("pubsub_service_account_email") or "").strip()
        if not service_account_email:
            return False
        authorization = headers.get("Authorization") or headers.get("authorization") or ""
        if not authorization.lower().startswith("bearer "):
            return False
        token = authorization.split(" ", 1)[1].strip()
        try:
            jwks = fetch_google_jwks(self.http, self._jwks_cache)
            try:
                verify_google_id_token(
                    token, audience=audience, jwks=jwks, service_account_email=service_account_email
                )
            except UnknownKeyIdError:
                # Google a rotit cheile: o singura reincarcare fortata, apoi inca o verificare.
                jwks = fetch_google_jwks(self.http, self._jwks_cache, force=True)
                verify_google_id_token(
                    token, audience=audience, jwks=jwks, service_account_email=service_account_email
                )
            return True
        except GooglePlayWebhookError:
            return False
        except Exception:
            # Fail closed: stratul HTTP raspunde 401, Pub/Sub reincearca.
            return False

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        try:
            envelope = json.loads(body)
        except (ValueError, TypeError) as exc:
            raise GooglePlayWebhookError(f"Corp Pub/Sub invalid: {exc}") from exc
        message = envelope.get("message") if isinstance(envelope, dict) else None
        if not isinstance(message, dict):
            raise GooglePlayWebhookError("Lipseste `message` din push-ul Pub/Sub")
        return webhook_event_from_pubsub(message)
