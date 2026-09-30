"""
Altex Marketplace API client — per-request SHA-512 signature, envelope parsing.

Signature (spec, `X-Request-Signature`):
    params = query params for GET/DELETE, body params for POST/PUT (minus the `media` file)
    params_str = http_build_query(params, '', '|', PHP_QUERY_RFC3986)
    ddmm = date('dm') in UTC
    signature = ddmm + sha512_hex(public + "||" + sha512_hex(private) + "||" + params_str + "||" + ddmm)

The JSON body is signed as the server will see it after json_decode, so the same dict
is both signed and sent.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

import requests

from bapp_connectors.core.errors import AuthenticationError, ProviderError

if TYPE_CHECKING:
    from bapp_connectors.core.http import ResilientHttpClient


class AltexApiError(ProviderError):
    """Altex answered status "error" (or a 4xx); the message is what it said."""


def _php_scalar(value) -> str:
    """How PHP's http_build_query renders a json_decode'd scalar."""
    if value is True:
        return "1"
    if value is False:
        return "0"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _flatten(obj, prefix: str = ""):
    items = obj.items() if isinstance(obj, dict) else enumerate(obj)
    for key, value in items:
        encoded = quote(str(key), safe="-_.~")
        name = f"{prefix}%5B{encoded}%5D" if prefix else encoded
        if value is None:
            continue  # http_build_query skips nulls
        if isinstance(value, (dict, list, tuple)):
            yield from _flatten(value, name)
        else:
            yield f"{name}={quote(_php_scalar(value), safe='-_.~')}"


def build_query(params: dict | None) -> str:
    return "|".join(_flatten(params or {}))


def sign(public_key: str, private_key: str, params: dict | None, when: datetime | None = None) -> str:
    ddmm = (when or datetime.now(UTC)).strftime("%d%m")
    private_hash = hashlib.sha512(private_key.encode()).hexdigest()
    payload = f"{public_key}||{private_hash}||{build_query(params)}||{ddmm}"
    return ddmm + hashlib.sha512(payload.encode()).hexdigest()


class AltexApiClient:
    def __init__(self, http_client: ResilientHttpClient, base_url: str, public_key: str, private_key: str):
        self.http = http_client
        self.base_url = base_url.rstrip("/") + "/"
        self.public_key = public_key
        self.private_key = private_key

    def _call(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None,
              form: dict | None = None, files: dict | None = None, **kwargs) -> Any:
        signed = params if method in ("GET", "DELETE") else (json if json is not None else form)
        headers = {
            "X-Request-Public-Key": self.public_key,
            "X-Request-Signature": sign(self.public_key, self.private_key, signed),
            "Accept": "application/json",
        }
        call_kwargs: dict = {"params": params} if params else {}
        if json is not None:
            call_kwargs["json"] = json
        if form is not None:
            call_kwargs["data"] = _form_fields(form)
        if files is not None:
            call_kwargs["files"] = files
        try:
            response = self.http.call(method, self.base_url + path, headers=headers, direct_response=True,
                                      **call_kwargs, **kwargs)
        except requests.RequestException as exc:
            raise ProviderError(f"Altex {method} {path} failed: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            raise ProviderError(f"Altex {path}: HTTP {response.status_code} {response.text[:200]}",
                                status_code=response.status_code) from None
        if response.status_code == 401:
            raise AuthenticationError(f"Altex: {_message(body) or 'Access Denied.'}")
        if response.status_code >= 400 or (isinstance(body, dict) and body.get("status") == "error"):
            raise AltexApiError(f"Altex {path}: {_message(body) or response.status_code}",
                                status_code=response.status_code)
        return body.get("data") if isinstance(body, dict) else body

    # ── Orders ──

    def list_orders(self, start_date: str = "", end_date: str = "", status: int | None = None,
                    page: int = 1, per_page: int = 100) -> dict:
        params: dict = {"page_nr": page, "items_per_page": per_page}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if status is not None:
            params["status"] = status
        return self._call("GET", "sales/order/", params=params) or {}

    def get_order(self, order_id: str) -> dict:
        return self._call("GET", f"sales/order/{order_id}/") or {}

    def update_order_status(self, order_id: str, status: int, cancellation_reason: int | None = None) -> None:
        body: dict = {"status": status}
        if cancellation_reason is not None:
            body["cancellationReason"] = cancellation_reason
        self._call("PUT", f"sales/order/{order_id}/", json=body, retry=False, log_body=True)

    def upload_invoice(self, order_id: str, pdf: bytes, invoice_number: str, name: str, line_ids: list) -> None:
        form = {"name": name, "invoice_number": invoice_number, "products": [str(i) for i in line_ids]}
        self._call("POST", f"sales/order/{order_id}/invoice/", form=form,
                   files={"media": (f"{name}.pdf", pdf, "application/pdf")}, retry=False, log_body=True)

    def attach_awb(self, order_id: str, pdf: bytes, number: str, courier_id: int) -> None:
        form = {"number": str(number), "courier_id": str(courier_id)}
        self._call("POST", f"sales/order/{order_id}/awb/", form=form,
                   files={"media": (f"awb_{number}.pdf", pdf, "application/pdf")}, retry=False, log_body=True)

    def couriers(self) -> list[dict]:
        return _items(self._call("GET", "sales/courier/"))

    def locations(self) -> list[dict]:
        """Pickup locations; the docs say {id, courier_id, ...}, real answers {courier_location_id, address}."""
        return _items(self._call("GET", "sales/location/"))

    def regions(self) -> list[dict]:
        return _items(self._call("GET", "sales/region/", params={"page_nr": 1, "items_per_page": 100}))

    def localities(self, region_id: int) -> list[dict]:
        out, page = [], 1
        while True:
            data = self._call("GET", "sales/locality/", params={"region_id": region_id, "page_nr": page,
                                                                "items_per_page": 500}) or {}
            out += _items(data)
            if not isinstance(data, dict) or int(data.get("current_page") or page) >= int(data.get("total_pages") or page):
                return out
            page += 1

    def generate_awb(self, order_id: str, form: dict) -> dict:
        """Altex books the courier; never retried (a retry could book a second AWB)."""
        return self._call("POST", f"sales/order/{order_id}/awb/generate", form=form, retry=False,
                          log_body=True) or {}

    # ── Returns (RMA) ──

    def list_rmas(self, created_from: str = "", page: int = 1, per_page: int = 100) -> dict:
        params: dict = {"page_nr": page, "items_per_page": per_page}
        if created_from:
            params["created_at"] = created_from
        return self._call("GET", "sales/rma/", params=params) or {}

    def get_rma(self, rma_id: str) -> dict:
        return self._call("GET", f"sales/rma/{rma_id}/") or {}

    # ── Offers ──

    def list_offers(self, page: int = 1, per_page: int = 100, updated_from: str = "") -> dict:
        params: dict = {"page_nr": page, "items_per_page": per_page}
        if updated_from:
            params["updated_from"] = updated_from
        return self._call("GET", "catalog/offer/", params=params) or {}

    def update_offer(self, offer_id: str, fields: dict) -> None:
        self._call("PUT", f"catalog/offer/{offer_id}/", json=fields, retry=False, log_body=True)

    def update_offer_stock(self, offer_id: str, stock: int) -> None:
        self._call("PUT", f"catalog/offer/{offer_id}/stock/", json={"stock": int(stock)}, retry=False,
                   log_body=True)


def _items(data) -> list[dict]:
    """Lists come paginated ({items: [...]}) per the docs, but plain in some real answers."""
    if isinstance(data, dict):
        return data.get("items") or []
    return data if isinstance(data, list) else []


def _form_fields(form: dict) -> list[tuple[str, str]]:
    """Multipart fields as PHP reads them: a list becomes repeated `key[]` fields, which
    json-less PHP turns back into the array the signature was computed on."""
    fields = []
    for key, value in form.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            fields += [(f"{key}[]", _php_scalar(v)) for v in value]
        else:
            fields.append((key, _php_scalar(value)))
    return fields


def _message(body) -> str:
    message = body.get("message") if isinstance(body, dict) else body
    if isinstance(message, list):
        return "; ".join(map(str, message))
    if isinstance(message, dict):
        parts = []
        for key, value in message.items():
            if isinstance(value, dict):
                parts += [f"{key}[{k}]: {v}" for k, v in value.items()]
            else:
                parts.append(f"{key}: {value}")
        return "; ".join(parts)
    return str(message or "")
