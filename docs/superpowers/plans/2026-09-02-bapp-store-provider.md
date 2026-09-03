# bapp_store shop provider (bapp-connectors 0.29.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `bapp_store` shop provider to `bapp-connectors` so a BAPP panel can push its catalogue (categories, products, gross prices, quantity price tiers), push shop-wide volume-pricing rules, and pull orders back from a Company Store tenant storefront. Ship it as release 0.29.0 together with the four core additions the provider needs. `ShopPort` declares `get_products` abstract, so the adapter implements a paged read of the store catalogue as well; that one method is a port requirement, not a v1 feature, because spec section 12 defers pulling products from the store.

**Architecture:** `bapp_connectors` is a pure-Python ports-and-adapters integration framework with no Django dependency. An adapter implements a port (`ShopPort`, `src/bapp_connectors/core/ports/shop.py:19`) plus optional capability ABCs (`src/bapp_connectors/core/capabilities/`), and registers itself with a global registry on package import. DTOs are frozen pydantic models (`BaseDTO`, `src/bapp_connectors/core/dto/base.py:26`). Every provider is 7 files: `manifest.py` (declarative config), `client.py` (raw HTTP through `ResilientHttpClient`), `adapter.py` (port + capabilities), `mappers.py` (provider payloads <-> DTOs), `models.py` (pydantic shapes of raw payloads), `errors.py` (status -> framework error), `__init__.py` (registration). This provider adds an eighth directory, `fixtures/`, holding the cross-repo contract samples shared with the company-store and aio-backend repos.

The store side is a bapp_framework app: reads go through public content-type viewsets (`content-type/store.storecategory/`, `content-type/store.storeproduct/`), writes go through one DirectTask (`tasks/store.CatalogSyncTask`) that accepts `categories`, `products`, `rules` and `webhook` in a single envelope and answers positionally. Orders come back through two export tasks. The store stores GROSS prices only; the framework convention is NET, so the mappers convert in both directions with `to_gross` / `to_net` (`src/bapp_connectors/core/pricing.py:22` and `:36`).

**Tech Stack:** Python 3.11+, pydantic v2, requests, pytest, uv. No new runtime dependencies.

**Spec:** `/Users/johnyb/projects/bapp-cloud/micro-saas/company-store/docs/superpowers/specs/2026-09-02-bapp-store-connector-design.md` -- sections 2.1 (core additions), 2.2 (provider package), 2.3 (Product DTO extra convention), 4.1 (CatalogSyncTask contract), 4.7 (orders export and webhook), 5 (pricing semantics and worked example), 8 (error handling).

## Global Constraints

- **Repo root for every path and command:** `/Users/johnyb/projects/bapp-cloud/packages/connectors`. Run every command from that directory.
- **Version:** `pyproject.toml:3` is `version = "0.28.3"` today and becomes `0.29.0` in the last task. `uv.lock` line 47 repeats it under `name = "bapp-connectors"` and is regenerated with `uv lock`.
- **Test command:** `uv run --extra dev pytest tests/shop/bapp_store -v` for the provider, `uv run --extra dev pytest tests/core -v` for the core changes. Integration tests are auto-skipped (`addopts = "-m 'not integration'"`); nothing here needs a live store.
- **Naming, fixed across every task:** package `src/bapp_connectors/providers/shop/bapp_store/`, manifest `name="bapp_store"`, `display_name="Company Store (BAPP)"`, adapter class `BappStoreShopAdapter`, client class `BappStoreClient`, tests under `tests/shop/bapp_store/`.
- **Credentials:** `store_url` (role `endpoint`, not sensitive), `token` (sensitive).
- **Settings and defaults:** `prices_include_vat` bool `True`, `vat_rate` str `"0.21"`, `batch_size` int `100`, `pause_seconds` int `1`, `publish_status` select `publish|draft` default `"publish"`, `sync_images` bool `True`.
- **Transport:** `base_url = store_url.rstrip("/") + "/api/"`; every call carries `Authorization: Token <token>` and `X-App-Slug: sync`.
- **Paging:** the store's content-type viewsets are DRF `PageNumberPagination` pages (`count`, `next`, `previous`, `results`), selected with the query params `page` and `page_size` (`DefaultPagination.max_page_size = 100`, hence `PAGE_LIMIT = 100`). `find_products(page=N)` sends `{"page_size": 100, "page": N}`. There is no `limit` or `offset` query parameter against a content-type viewset anywhere in this provider; `limit` belongs to the order export tasks alone (spec 4.7).
- **Product lookup by code:** `find_products(code=...)` needs `code` declared in the store's `StoreProduct.api_options.filterset_fields` (widened by the company-store plan). DRF drops a query parameter the filterset does not declare, so without it the store answers with an unfiltered first page and `find_product_by_sku` adopts nothing.
- **`update_category` keeps the base-class signature** `update_category(self, category: ProductCategory) -> ProductCategory` (`src/bapp_connectors/core/capabilities/product_management.py:58`), because `ProductSyncEngine` calls it with a `ProductCategory` (`src/bapp_connectors/core/sync/engine.py:268`). `create_category` is the method that gains `local_id`. This supersedes the three-argument `update_category(category_id, name=None, parent_id=None)` shape used elsewhere in the design notes: the engine at `src/bapp_connectors/core/sync/engine.py:268` constructs a `ProductCategory` and passes it positionally, so only the base-class signature works. Consumers must not call the three-argument form.
- **`FakeHttpClient` facts that shape the tests** (`tests/fake_http.py:41`): `call(self, method, path, direct_response=False, headers=None, **kwargs)` records `RecordedCall(method, path, {"headers": headers, **kwargs})`. `direct_response` is a named parameter and is therefore NOT in the recorded kwargs; `retry` and `timeout` are. A canned response is returned as-is, so any POST to `tasks/store.CatalogSyncTask` must be canned as a `FakeResponse` (the client calls `.ok` / `.json()` on it), while GET responses are canned as plain dicts.
- **Commit messages:** plain ASCII, subject line only, no body, no trailers, no emojis. Commit exactly the files each task lists.
- **Docs:** plain ASCII, no em-dashes, no Unicode arrows; write `->` and `--`.
- **Code:** production-grade. Comments only where a non-obvious WHY needs one line.

---

## File Structure

Created:

| Path | Responsibility |
|------|----------------|
| `src/bapp_connectors/core/dto/shop_rules.py` | `ShopRules` and `OrderValueTier` DTOs |
| `src/bapp_connectors/core/capabilities/volume_pricing.py` | `VolumePricingCapability` ABC |
| `src/bapp_connectors/providers/shop/bapp_store/__init__.py` | Package docstring, then registry registration |
| `src/bapp_connectors/providers/shop/bapp_store/manifest.py` | Credentials, settings, capabilities, rate limit, webhook config |
| `src/bapp_connectors/providers/shop/bapp_store/errors.py` | HTTP status -> framework error |
| `src/bapp_connectors/providers/shop/bapp_store/models.py` | Pydantic shapes of the CatalogSyncTask response |
| `src/bapp_connectors/providers/shop/bapp_store/client.py` | Raw HTTP against the store's `/api/` surface |
| `src/bapp_connectors/providers/shop/bapp_store/mappers.py` | DTO <-> store payload conversion, both directions |
| `src/bapp_connectors/providers/shop/bapp_store/adapter.py` | `BappStoreShopAdapter`: port + capabilities |
| `src/bapp_connectors/providers/shop/bapp_store/README.md` | Provider documentation |
| `src/bapp_connectors/providers/shop/bapp_store/fixtures/__init__.py` | Makes the fixtures importable-resource addressable |
| `src/bapp_connectors/providers/shop/bapp_store/fixtures/products_batch.json` | Cross-repo sample of one catalogue batch and its response |
| `src/bapp_connectors/providers/shop/bapp_store/fixtures/rules.json` | Cross-repo sample of the rules envelope and its policy hash |
| `src/bapp_connectors/providers/shop/bapp_store/fixtures/orders_export.json` | Cross-repo sample of one exported order page |
| `src/bapp_connectors/providers/shop/bapp_store/fixtures/pricing_cases.json` | Cross-repo pricing parity cases |
| `tests/core/test_volume_pricing.py` | `ShopRules` DTO and `VolumePricingCapability` tests |
| `tests/core/test_engine_category_local_id.py` | Engine passes `local_id` only to opted-in adapters |
| `tests/shop/bapp_store/__init__.py` | Test package marker |
| `tests/shop/bapp_store/fake_response.py` | `requests.Response` stand-in for `direct_response=True` calls |
| `tests/shop/bapp_store/test_fixtures_parity.py` | Fixtures parse; gross rounding matches the store |
| `tests/shop/bapp_store/test_manifest.py` | Manifest and registration tests |
| `tests/shop/bapp_store/test_errors_unit.py` | Error mapping tests |
| `tests/shop/bapp_store/test_client_unit.py` | Raw payload models and client tests |
| `tests/shop/bapp_store/test_mappers_unit.py` | Product, category, rules, bulk and inbound mapper tests |
| `tests/shop/bapp_store/test_orders_unit.py` | Order mapper and adapter order-path tests |
| `tests/shop/bapp_store/test_adapter_unit.py` | Adapter tests against `FakeHttpClient` |

Modified:

| Path | Change |
|------|--------|
| `src/bapp_connectors/core/dto/__init__.py` | Export `ShopRules`, `OrderValueTier` |
| `src/bapp_connectors/core/capabilities/__init__.py` | Export `VolumePricingCapability` |
| `src/bapp_connectors/core/capabilities/product_management.py` | `CategoryManagementCapability.accepts_local_category_id` |
| `src/bapp_connectors/core/sync/engine.py` | `sync_categories` passes `local_id` when the adapter accepts it |
| `src/bapp_connectors/core/ports/shop.py` | `ShopPort.sideloads_images` |
| `tests/core/test_shop_port_since.py` | One test for `sideloads_images` |
| `docs/PROVIDER_GUIDE.md` | Capability table row plus three notes |
| `pyproject.toml`, `uv.lock` | Version 0.29.0 |
| `README.md` | Regenerated providers table and structure tree |

---

## Tasks

### Task 1: Cross-repo fixture files

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/fixtures/__init__.py` (empty)
- Create: `src/bapp_connectors/providers/shop/bapp_store/fixtures/products_batch.json`
- Create: `src/bapp_connectors/providers/shop/bapp_store/fixtures/rules.json`
- Create: `src/bapp_connectors/providers/shop/bapp_store/fixtures/orders_export.json`
- Create: `src/bapp_connectors/providers/shop/bapp_store/fixtures/pricing_cases.json`
- Create: `tests/shop/bapp_store/__init__.py` (empty)
- Test: `tests/shop/bapp_store/test_fixtures_parity.py`

**Interfaces**
- Consumes: nothing.
- Produces: the four JSON files. Later tasks read them either with `json.loads(Path("src/bapp_connectors/providers/shop/bapp_store/fixtures/<name>").read_text())` or with `importlib.resources.files("bapp_connectors.providers.shop.bapp_store") / "fixtures"`. `src/bapp_connectors/providers/shop/bapp_store/fixtures/` is the canonical home of the four files: the company-store and aio-backend repos take their copies from here (spec sections 4.1 and 4.7) and never hand-edit them. Copies are compared by parsed structure (`json.loads`), not by digest, because a copy may differ by a trailing newline. `tests/shop/bapp_store/__init__.py` is created here once and never re-created by a later task.

- [ ] **Step 1: Write the failing test** at `tests/shop/bapp_store/test_fixtures_parity.py`:

```python
"""Fixture parity: the JSON files under the package are the cross-repo contract."""
import json
from pathlib import Path

FIXTURES = Path("src/bapp_connectors/providers/shop/bapp_store/fixtures")


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_fixture_files_exist_and_parse():
    batch = _load("products_batch.json")
    rules = _load("rules.json")
    orders = _load("orders_export.json")
    cases = _load("pricing_cases.json")
    assert [c["id"] for c in batch["request"]["categories"]] == ["159", "160"]
    assert [p["code"] for p in batch["request"]["products"]] == ["CIO-500", "BAL-60", "BUR-10"]
    assert rules["request"]["rules"]["min_order_total"] == "1000.00"
    assert orders["items"][0]["number"] == "ORD-000123"
    assert [c["name"] for c in cases["cases"]] == [
        "worked_example",
        "below_minimum",
        "category_ancestor_rule",
        "non_discountable_no_ladder",
        "half_up_tier_no_vat",
        "no_rules_at_all",
    ]
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_fixtures_parity.py -v
```

Expected: collection succeeds, the test fails with `FileNotFoundError: [Errno 2] No such file or directory: 'src/bapp_connectors/providers/shop/bapp_store/fixtures/products_batch.json'`.

- [ ] **Step 3: Write the fixtures verbatim**

These four files are the contract. Paste them exactly as written below; do not reformat, reorder keys or change any decimal string. The heredocs add a trailing newline that the originals do not have, so verify them by parsed structure (Step 4), never by byte hash. This directory is the canonical copy the company-store and aio-backend repos take theirs from.

```bash
mkdir -p src/bapp_connectors/providers/shop/bapp_store/fixtures tests/shop/bapp_store
touch src/bapp_connectors/providers/shop/bapp_store/fixtures/__init__.py tests/shop/bapp_store/__init__.py
cat > src/bapp_connectors/providers/shop/bapp_store/fixtures/products_batch.json <<'JSON'
{
 "request": {
  "categories": [
   {
    "id": "159",
    "parent_id": null,
    "name": "Scule",
    "is_active": true
   },
   {
    "id": "160",
    "parent_id": "159",
    "name": "Burghie",
    "is_active": true
   }
  ],
  "products": [
   {
    "id": "345100",
    "name": "Ciocan 500 g",
    "code": "CIO-500",
    "code_ean": "5941234567890",
    "unit": "buc",
    "description": "Ciocan cu coada de lemn.",
    "price": {
     "amount": "114.95",
     "currency": "RON"
    },
    "stock": "42",
    "is_active": true,
    "category_ids": [
     "159"
    ],
    "primary_category": "159",
    "price_tiers": [
     {
      "min_quantity": "10",
      "price_amount": "109.20"
     },
     {
      "min_quantity": "50",
      "price_amount": "105.75"
     }
    ],
    "extra": {
     "bapp": {
      "gross_price": "114.95",
      "vat_rate": "21",
      "unit": "buc",
      "discountable": true
     }
    },
    "photos": [
     {
      "url": "https://cdn.example.com/p/345100-0.jpg",
      "order": 0
     }
    ]
   },
   {
    "id": "345101",
    "name": "Balama 60 mm",
    "code": "BAL-60",
    "code_ean": "",
    "unit": "buc",
    "description": "",
    "price": {
     "amount": "80.47",
     "currency": "RON"
    },
    "stock": "0",
    "is_active": true,
    "category_ids": [
     "159"
    ],
    "primary_category": "159",
    "price_tiers": [],
    "extra": {
     "bapp": {
      "gross_price": "80.47",
      "vat_rate": "21",
      "unit": "buc",
      "discountable": true
     }
    },
    "photos": [
     {
      "url": "https://cdn.example.com/p/345101-0.jpg",
      "order": 0
     }
    ]
   },
   {
    "id": "345102",
    "name": "Set burghie 10 buc",
    "code": "BUR-10",
    "code_ean": "",
    "unit": "buc",
    "description": "",
    "price": {
     "amount": "60.50",
     "currency": "RON"
    },
    "stock": "5",
    "is_active": true,
    "category_ids": [
     "160"
    ],
    "primary_category": "160",
    "price_tiers": [],
    "extra": {
     "bapp": {
      "gross_price": "60.50",
      "vat_rate": "21",
      "unit": "buc",
      "discountable": false
     }
    }
   }
  ]
 },
 "response": {
  "categories": [
   {
    "index": 0,
    "id": "159",
    "status": "created",
    "error": "",
    "code": ""
   },
   {
    "index": 1,
    "id": "160",
    "status": "created",
    "error": "",
    "code": ""
   }
  ],
  "products": [
   {
    "index": 0,
    "id": "345100",
    "status": "created",
    "error": "",
    "code": ""
   },
   {
    "index": 1,
    "id": "345101",
    "status": "created",
    "error": "",
    "code": ""
   },
   {
    "index": 2,
    "id": "345102",
    "status": "created",
    "error": "",
    "code": ""
   }
  ],
  "rules_applied": false,
  "webhook_applied": false
 }
}
JSON
cat > src/bapp_connectors/providers/shop/bapp_store/fixtures/rules.json <<'JSON'
{
 "policy_hash_recipe": "sha256 of json.dumps({'order_value_tiers': [...], 'min_order_total': '...'}, sort_keys=True, separators=(',', ':'))",
 "request": {
  "rules": {
   "order_value_tiers": [
    {
     "min_total": "5000.00",
     "discount_percent": "3.00"
    },
    {
     "min_total": "10000.00",
     "discount_percent": "5.00"
    }
   ],
   "min_order_total": "1000.00",
   "currency": "RON",
   "connection_id": 123,
   "policy_hash": "d781e2f107f3407972917f4a8e84964540086a7f5ad91620de9f4f8536d885b1",
   "synced_at": "2026-09-02T12:00:00+03:00"
  }
 },
 "response": {
  "categories": [],
  "products": [],
  "rules_applied": true,
  "webhook_applied": false
 }
}
JSON
cat > src/bapp_connectors/providers/shop/bapp_store/fixtures/orders_export.json <<'JSON'
{
 "items": [
  {
   "number": "ORD-000123",
   "created_at": "2026-09-02T14:05:00+03:00",
   "updated_at": "2026-09-02T14:05:00+03:00",
   "status": "pending",
   "payment_status": "unpaid",
   "payment_type": "bank_transfer",
   "currency": "RON",
   "billing": {
    "company_name": "ACME SRL",
    "vat_id": "RO12345678",
    "reg_com": "J12/345/2020",
    "name": "Ana Pop",
    "email": "ana@acme.example",
    "phone": "0712345678",
    "address": "Strada Firmei 9",
    "city": "Cluj-Napoca",
    "county": "Cluj",
    "postal_code": "400001"
   },
   "delivery_address": "Strada Firmei 9, Cluj-Napoca, Cluj, 400001",
   "notes": "Livrare dupa ora 10",
   "items": [
    {
     "product_id": "345100",
     "sku": "CIO-500",
     "name": "Ciocan 500 g",
     "quantity": "60",
     "unit_price": "114.95",
     "currency": "RON",
     "extra": {
      "unit_tier": "105.75",
      "line_total": "6027.75"
     }
    },
    {
     "product_id": "345101",
     "sku": "BAL-60",
     "name": "Balama 60 mm",
     "quantity": "50",
     "unit_price": "80.47",
     "currency": "RON",
     "extra": {
      "unit_tier": "80.47",
      "line_total": "3822.33"
     }
    }
   ],
   "total": "9850.08",
   "goods_total": "9850.08",
   "shipping_total": "0.00",
   "extra": {
    "policy_hash": "d781e2f107f3407972917f4a8e84964540086a7f5ad91620de9f4f8536d885b1",
    "volume_discount_total": "518.42",
    "value_pct": "5.00",
    "order_url": "https://zogjaemtbppsfb0-st.sites.bapp.ro/account/orders/ORD-000123"
   }
  }
 ],
 "cursor": null,
 "has_more": false
}
JSON
cat > src/bapp_connectors/providers/shop/bapp_store/fixtures/pricing_cases.json <<'JSON'
{
 "description": "Cross-repo pricing parity cases: gross_list, ladder, from_price, order value, value percent, line totals. Amounts are gross RON strings, ROUND_HALF_UP to 2dp. Rules: product rows win outright; else category rows over the product category and its ancestors, best percent per threshold; non-discountable products get no ladder, count toward the order value and receive no value percent (from_price null). Value percent is applied per line on unit_q x qty.",
 "cases": [
  {
   "name": "worked_example",
   "price_modifier": "-5%",
   "products": {
    "P": {
     "net": "100.0000",
     "tax": "21",
     "discountable": true,
     "category": "scule"
    },
    "Q": {
     "net": "70.0000",
     "tax": "21",
     "discountable": true,
     "category": "feronerie"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {
     "P": [
      [
       "10",
       "5"
      ],
      [
       "50",
       "8"
      ]
     ]
    },
    "category": {
     "scule": [
      [
       "20",
       "6"
      ]
     ]
    },
    "order": [
     [
      "5000.00",
      "3"
     ],
     [
      "10000.00",
      "5"
     ]
    ]
   },
   "min_order_total": "1000.00",
   "lines": [
    [
     "P",
     "60"
    ],
    [
     "Q",
     "50"
    ]
   ],
   "expected": {
    "products": {
     "P": {
      "gross_list": "114.95",
      "ladder": [
       [
        "10",
        "109.20"
       ],
       [
        "50",
        "105.75"
       ]
      ],
      "from_price": "100.46"
     },
     "Q": {
      "gross_list": "80.47",
      "ladder": [],
      "from_price": "76.45"
     }
    },
    "order_value": "10368.50",
    "value_pct": "5.00",
    "lines": [
     [
      "P",
      "105.75",
      "6027.75"
     ],
     [
      "Q",
      "80.47",
      "3822.33"
     ]
    ],
    "goods_total": "9850.08",
    "volume_discount_total": "518.42",
    "meets_minimum": true,
    "missing_amount": "0.00"
   }
  },
  {
   "name": "below_minimum",
   "price_modifier": "-5%",
   "products": {
    "P": {
     "net": "100.0000",
     "tax": "21",
     "discountable": true,
     "category": "scule"
    },
    "Q": {
     "net": "70.0000",
     "tax": "21",
     "discountable": true,
     "category": "feronerie"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {
     "P": [
      [
       "10",
       "5"
      ],
      [
       "50",
       "8"
      ]
     ]
    },
    "category": {
     "scule": [
      [
       "20",
       "6"
      ]
     ]
    },
    "order": [
     [
      "5000.00",
      "3"
     ],
     [
      "10000.00",
      "5"
     ]
    ]
   },
   "min_order_total": "1000.00",
   "lines": [
    [
     "P",
     "3"
    ],
    [
     "Q",
     "5"
    ]
   ],
   "expected": {
    "products": {
     "P": {
      "gross_list": "114.95",
      "ladder": [
       [
        "10",
        "109.20"
       ],
       [
        "50",
        "105.75"
       ]
      ],
      "from_price": "100.46"
     },
     "Q": {
      "gross_list": "80.47",
      "ladder": [],
      "from_price": "76.45"
     }
    },
    "order_value": "747.20",
    "value_pct": "0.00",
    "lines": [
     [
      "P",
      "114.95",
      "344.85"
     ],
     [
      "Q",
      "80.47",
      "402.35"
     ]
    ],
    "goods_total": "747.20",
    "volume_discount_total": "0.00",
    "meets_minimum": false,
    "missing_amount": "252.80"
   }
  },
  {
   "name": "category_ancestor_rule",
   "price_modifier": "-5%",
   "products": {
    "U": {
     "net": "10.0000",
     "tax": "21",
     "discountable": true,
     "category": "burghie"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {
     "P": [
      [
       "10",
       "5"
      ],
      [
       "50",
       "8"
      ]
     ]
    },
    "category": {
     "scule": [
      [
       "20",
       "6"
      ]
     ]
    },
    "order": [
     [
      "5000.00",
      "3"
     ],
     [
      "10000.00",
      "5"
     ]
    ]
   },
   "min_order_total": "0.00",
   "lines": [
    [
     "U",
     "25"
    ]
   ],
   "expected": {
    "products": {
     "U": {
      "gross_list": "11.50",
      "ladder": [
       [
        "20",
        "10.81"
       ]
      ],
      "from_price": "10.27"
     }
    },
    "order_value": "270.25",
    "value_pct": "0.00",
    "lines": [
     [
      "U",
      "10.81",
      "270.25"
     ]
    ],
    "goods_total": "270.25",
    "volume_discount_total": "0.00",
    "meets_minimum": true,
    "missing_amount": "0.00"
   }
  },
  {
   "name": "non_discountable_no_ladder",
   "price_modifier": "-5%",
   "products": {
    "T": {
     "net": "50.0000",
     "tax": "21",
     "discountable": false,
     "category": "scule"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {
     "P": [
      [
       "10",
       "5"
      ],
      [
       "50",
       "8"
      ]
     ]
    },
    "category": {
     "scule": [
      [
       "20",
       "6"
      ]
     ]
    },
    "order": [
     [
      "5000.00",
      "3"
     ],
     [
      "10000.00",
      "5"
     ]
    ]
   },
   "min_order_total": "0.00",
   "lines": [
    [
     "T",
     "100"
    ]
   ],
   "expected": {
    "products": {
     "T": {
      "gross_list": "57.48",
      "ladder": [],
      "from_price": null
     }
    },
    "order_value": "5748.00",
    "value_pct": "3.00",
    "lines": [
     [
      "T",
      "57.48",
      "5748.00"
     ]
    ],
    "goods_total": "5748.00",
    "volume_discount_total": "0.00",
    "meets_minimum": true,
    "missing_amount": "0.00"
   }
  },
  {
   "name": "half_up_tier_no_vat",
   "price_modifier": "",
   "products": {
    "S": {
     "net": "20.3000",
     "tax": "0",
     "discountable": true,
     "category": "diverse"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {
     "S": [
      [
       "5",
       "5"
      ]
     ]
    },
    "category": {},
    "order": []
   },
   "min_order_total": "0.00",
   "lines": [
    [
     "S",
     "5"
    ]
   ],
   "expected": {
    "products": {
     "S": {
      "gross_list": "20.30",
      "ladder": [
       [
        "5",
        "19.29"
       ]
      ],
      "from_price": "19.29"
     }
    },
    "order_value": "96.45",
    "value_pct": "0.00",
    "lines": [
     [
      "S",
      "19.29",
      "96.45"
     ]
    ],
    "goods_total": "96.45",
    "volume_discount_total": "0.00",
    "meets_minimum": true,
    "missing_amount": "0.00"
   }
  },
  {
   "name": "no_rules_at_all",
   "price_modifier": "",
   "products": {
    "Q": {
     "net": "70.0000",
     "tax": "21",
     "discountable": true,
     "category": "feronerie"
    }
   },
   "categories": {
    "scule": null,
    "feronerie": null,
    "burghie": "scule",
    "diverse": null
   },
   "rules": {
    "product": {},
    "category": {},
    "order": []
   },
   "min_order_total": "0.00",
   "lines": [
    [
     "Q",
     "1"
    ]
   ],
   "expected": {
    "products": {
     "Q": {
      "gross_list": "84.70",
      "ladder": [],
      "from_price": null
     }
    },
    "order_value": "84.70",
    "value_pct": "0.00",
    "lines": [
     [
      "Q",
      "84.70",
      "84.70"
     ]
    ],
    "goods_total": "84.70",
    "volume_discount_total": "0.00",
    "meets_minimum": true,
    "missing_amount": "0.00"
   }
  }
 ]
}
JSON
```

- [ ] **Step 4: Run the test, confirm it passes**

```
uv run python -c "import json,pathlib; [json.loads(p.read_text()) for p in pathlib.Path('src/bapp_connectors/providers/shop/bapp_store/fixtures').glob('*.json')]"
uv run --extra dev pytest tests/shop/bapp_store/test_fixtures_parity.py -v
```

Expected: the `python -c` line prints nothing (all four files parse), then `test_fixture_files_exist_and_parse PASSED`, `1 passed`.

- [ ] **Step 5: Confirm the JSON files ship in the wheel**

`pyproject.toml:33-34` declares `[tool.hatch.build.targets.wheel] packages = ["src/bapp_connectors"]`, which packs every file under the package directory, JSON included. Verify:

```bash
WHEELDIR=$(mktemp -d)
uv build --wheel -o "$WHEELDIR" && unzip -l "$WHEELDIR"/*.whl | grep bapp_store/fixtures
```

Expected: four `.json` lines plus `__init__.py`.

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/fixtures tests/shop/bapp_store/__init__.py tests/shop/bapp_store/test_fixtures_parity.py
git commit -m "feat(bapp_store): ship the cross-repo contract fixtures"
```

---

### Task 2: ShopRules and OrderValueTier DTOs

**Files**
- Create: `src/bapp_connectors/core/dto/shop_rules.py`
- Modify: `src/bapp_connectors/core/dto/__init__.py` (import block after the `.shipment` import; `__all__` list)
- Test: `tests/core/test_volume_pricing.py` (new)

**Interfaces**
- Consumes: `BaseDTO` from `src/bapp_connectors/core/dto/base.py:26`.
- Produces:
  - `OrderValueTier(min_total: Decimal, discount_percent: Decimal)`, a frozen `BaseDTO`.
  - `ShopRules(order_value_tiers: list[OrderValueTier] = [], min_order_total: Decimal | None = None, currency: str = "", extra: dict = {})`, a frozen `BaseDTO`.
  - Both importable as `from bapp_connectors.core.dto import ShopRules, OrderValueTier`. Consumed by `mappers.rules_to_body(rules)` (Task 11) and `BappStoreShopAdapter.push_shop_rules(rules)` (Task 13).

- [ ] **Step 1: Write the failing test** at `tests/core/test_volume_pricing.py`:

```python
"""ShopRules DTO and VolumePricingCapability."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError


class TestShopRulesDTO:

    def test_order_value_tier_holds_decimals(self):
        from bapp_connectors.core.dto import OrderValueTier

        tier = OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00"))

        assert tier.min_total == Decimal("5000.00")
        assert tier.discount_percent == Decimal("3.00")

    def test_shop_rules_defaults(self):
        from bapp_connectors.core.dto import ShopRules

        rules = ShopRules()

        assert rules.order_value_tiers == []
        assert rules.min_order_total is None
        assert rules.currency == ""
        assert rules.extra == {}
        assert rules.provider_meta is None

    def test_shop_rules_is_frozen(self):
        from bapp_connectors.core.dto import ShopRules

        rules = ShopRules(currency="RON")

        with pytest.raises(ValidationError):
            rules.currency = "EUR"

    def test_shop_rules_full(self):
        from bapp_connectors.core.dto import OrderValueTier, ShopRules

        rules = ShopRules(
            order_value_tiers=[OrderValueTier(min_total=Decimal("1000"), discount_percent=Decimal("2"))],
            min_order_total=Decimal("500"),
            currency="RON",
            extra={"connection_id": 123},
        )

        assert rules.order_value_tiers[0].min_total == Decimal("1000")
        assert rules.min_order_total == Decimal("500")
        assert rules.extra["connection_id"] == 123
```

- [ ] **Step 2: Run the test, confirm it fails**

```
uv run --extra dev pytest tests/core/test_volume_pricing.py -v
```

Expected: 4 failures, each ending with `ImportError: cannot import name 'OrderValueTier' from 'bapp_connectors.core.dto'` (or `'ShopRules'`).

- [ ] **Step 3: Write the DTO module** at `src/bapp_connectors/core/dto/shop_rules.py`:

```python
"""
Shop-wide pricing rules pushed to a store that prices orders itself.
"""

from __future__ import annotations

from decimal import Decimal

from .base import BaseDTO


class OrderValueTier(BaseDTO):
    """Order-total discount step: gross order total >= min_total earns discount_percent."""

    min_total: Decimal
    discount_percent: Decimal


class ShopRules(BaseDTO):
    """Amounts are gross values in the store currency."""

    order_value_tiers: list[OrderValueTier] = []
    min_order_total: Decimal | None = None
    currency: str = ""
    extra: dict = {}
```

- [ ] **Step 4: Export from the dto package**

In `src/bapp_connectors/core/dto/__init__.py`, after the line `from .shipment import AWBLabel, Parcel, Shipment, ShipmentStatus, TrackingEvent` add:

```python
from .shop_rules import OrderValueTier, ShopRules
```

In the `__all__` list, insert `"OrderValueTier",` directly after `"OrderStatus",` and `"ShopRules",` directly after `"ShipmentStatus",` (the list is alphabetical).

- [ ] **Step 5: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/core/test_volume_pricing.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/core/dto/shop_rules.py src/bapp_connectors/core/dto/__init__.py tests/core/test_volume_pricing.py
git commit -m "feat(core): ShopRules and OrderValueTier DTOs"
```

---

### Task 3: VolumePricingCapability

**Files**
- Create: `src/bapp_connectors/core/capabilities/volume_pricing.py`
- Modify: `src/bapp_connectors/core/capabilities/__init__.py` (imports; `__all__`)
- Test: `tests/core/test_volume_pricing.py` (append a class)

**Interfaces**
- Consumes: `ShopRules` from Task 2.
- Produces: `class VolumePricingCapability(ABC)` with `@abstractmethod push_shop_rules(self, rules: ShopRules) -> None`, importable as `from bapp_connectors.core.capabilities import VolumePricingCapability` and as `from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability`. `BappStoreShopAdapter` (Task 13) inherits it, and the manifest (Task 6) lists it in `capabilities`.

- [ ] **Step 1: Write the failing test.** Append to `tests/core/test_volume_pricing.py`:

```python


class TestVolumePricingCapability:

    def test_is_abstract(self):
        from bapp_connectors.core.capabilities import VolumePricingCapability

        with pytest.raises(TypeError):
            VolumePricingCapability()

    def test_concrete_adapter_receives_rules(self):
        from bapp_connectors.core.capabilities import VolumePricingCapability
        from bapp_connectors.core.dto import ShopRules

        class _Adapter(VolumePricingCapability):
            def __init__(self):
                self.pushed: list[ShopRules] = []

            def push_shop_rules(self, rules: ShopRules) -> None:
                self.pushed.append(rules)

        adapter = _Adapter()
        rules = ShopRules(currency="RON", min_order_total=Decimal("1000"))
        adapter.push_shop_rules(rules)

        assert adapter.pushed == [rules]
        assert isinstance(adapter, VolumePricingCapability)
```

- [ ] **Step 2: Run the test, confirm it fails**

```
uv run --extra dev pytest tests/core/test_volume_pricing.py::TestVolumePricingCapability -v
```

Expected: 2 failures with `ImportError: cannot import name 'VolumePricingCapability' from 'bapp_connectors.core.capabilities'`.

- [ ] **Step 3: Write the capability** at `src/bapp_connectors/core/capabilities/volume_pricing.py`:

```python
"""
Volume pricing capability: the store applies quantity and order-value pricing itself.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import ShopRules


class VolumePricingCapability(ABC):
    """Adapter pushes shop-wide pricing rules and per-product quantity tiers.

    Convention for Product DTOs sent to such an adapter:
    ``extra["price_tiers"]`` is a list of ``{"min_quantity": str, "price": str}`` with
    materialised gross unit prices, and ``extra["bapp"]`` carries
    ``{"gross_price", "vat_rate", "unit", "discountable"}`` as strings/bools.
    """

    @abstractmethod
    def push_shop_rules(self, rules: ShopRules) -> None:
        """Replace the store's order-value tiers and minimum order total."""
        ...
```

- [ ] **Step 4: Export from the capabilities package**

In `src/bapp_connectors/core/capabilities/__init__.py`, after `from .transcription import TranscriptionCapability` add:

```python
from .volume_pricing import VolumePricingCapability
```

In `__all__`, insert `"VolumePricingCapability",` directly after `"VariantManagementCapability",`.

- [ ] **Step 5: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/core/test_volume_pricing.py -v
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/core/capabilities/volume_pricing.py src/bapp_connectors/core/capabilities/__init__.py tests/core/test_volume_pricing.py
git commit -m "feat(core): VolumePricingCapability"
```

---

### Task 4: accepts_local_category_id on the capability and the sync engine

**Files**
- Modify: `src/bapp_connectors/core/capabilities/product_management.py:46-60` (class `CategoryManagementCapability`)
- Modify: `src/bapp_connectors/core/sync/engine.py:271` (the `create_category` call inside `sync_categories`)
- Test: `tests/core/test_engine_category_local_id.py` (new)

**Interfaces**
- Consumes: `ProductSyncEngine.sync_categories(adapter, categories, existing_mappings=None, *, update_existing=False, remote_categories=None) -> CategorySyncResult` (`src/bapp_connectors/core/sync/engine.py:239`); `CategoryMapping(local_id, remote_id, name)` and `CategorySyncResult(created, updated)` (`src/bapp_connectors/core/sync/dto.py:34` and `:42`).
- Produces:
  - class attribute `CategoryManagementCapability.accepts_local_category_id: bool = False`.
  - Engine contract: when the adapter's `accepts_local_category_id` is True, `sync_categories` calls `adapter.create_category(name=category.name, parent_id=remote_parent_id, local_id=category.category_id)`; otherwise the call keeps `name=` and `parent_id=` only. Adapters that set the flag must accept `local_id: str | None = None`. `BappStoreShopAdapter.create_category(name, parent_id=None, local_id=None)` (Task 13) does, with `accepts_local_category_id = True`.

- [ ] **Step 1: Write the failing test** at `tests/core/test_engine_category_local_id.py`:

```python
"""sync_categories passes local_id only to adapters that opt in."""

from __future__ import annotations

from bapp_connectors.core.capabilities import CategoryManagementCapability
from bapp_connectors.core.dto import ConnectionTestResult, PaginatedResult, ProductCategory
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.sync import ProductSyncEngine


class _CategoryAdapter(ShopPort, CategoryManagementCapability):
    manifest = None  # type: ignore

    def __init__(self):
        self.calls: list[dict] = []

    def validate_credentials(self) -> bool:
        return True

    def test_connection(self) -> ConnectionTestResult:
        return ConnectionTestResult(success=True)

    def get_orders(self, since=None, cursor=None):
        return PaginatedResult(items=[])

    def get_order(self, order_id):
        raise NotImplementedError

    def get_products(self, cursor=None, since=None):
        return PaginatedResult(items=[])

    def update_product_stock(self, product_id, quantity):
        raise NotImplementedError

    def update_product_price(self, product_id, price, currency):
        raise NotImplementedError

    def update_order_status(self, order_id, status):
        raise NotImplementedError

    def get_categories(self) -> list[ProductCategory]:
        return []

    def create_category(self, name: str, parent_id: str | None = None) -> ProductCategory:
        self.calls.append({"name": name, "parent_id": parent_id})
        return ProductCategory(category_id=f"remote_{len(self.calls)}", name=name, parent_id=parent_id)


class _LocalIdAdapter(_CategoryAdapter):
    accepts_local_category_id = True

    def create_category(self, name: str, parent_id: str | None = None, local_id: str | None = None) -> ProductCategory:
        self.calls.append({"name": name, "parent_id": parent_id, "local_id": local_id})
        return ProductCategory(category_id=f"remote_{len(self.calls)}", name=name, parent_id=parent_id)


def test_capability_default_is_false():
    assert CategoryManagementCapability.accepts_local_category_id is False


def test_default_adapter_is_called_without_local_id():
    adapter = _CategoryAdapter()
    cats = [ProductCategory(category_id="loc_1", name="Doors")]

    result = ProductSyncEngine().sync_categories(adapter, cats)

    assert adapter.calls == [{"name": "Doors", "parent_id": None}]
    assert result.created[0].local_id == "loc_1"
    assert result.created[0].remote_id == "remote_1"


def test_opted_in_adapter_receives_local_id_and_remote_parent():
    adapter = _LocalIdAdapter()
    cats = [
        ProductCategory(category_id="loc_1", name="Doors"),
        ProductCategory(category_id="loc_2", name="Interior", parent_id="loc_1"),
    ]

    result = ProductSyncEngine().sync_categories(adapter, cats)

    assert adapter.calls == [
        {"name": "Doors", "parent_id": None, "local_id": "loc_1"},
        {"name": "Interior", "parent_id": "remote_1", "local_id": "loc_2"},
    ]
    assert [m.remote_id for m in result.created] == ["remote_1", "remote_2"]
```

- [ ] **Step 2: Run the test, confirm it fails**

```
uv run --extra dev pytest tests/core/test_engine_category_local_id.py -v
```

Expected: `test_capability_default_is_false` fails with `AttributeError: type object 'CategoryManagementCapability' has no attribute 'accepts_local_category_id'`; `test_opted_in_adapter_receives_local_id_and_remote_parent` fails with an `AssertionError` because the recorded calls carry `"local_id": None`; `test_default_adapter_is_called_without_local_id` passes.

- [ ] **Step 3: Add the flag to the capability**

In `src/bapp_connectors/core/capabilities/product_management.py`, replace the class header at lines 46-47:

```python
class CategoryManagementCapability(ABC):
    """Adapter supports reading and optionally creating categories."""
```

with:

```python
class CategoryManagementCapability(ABC):
    """Adapter supports reading and optionally creating categories."""

    #: True when create_category accepts `local_id` so the provider stores the caller's category id.
    accepts_local_category_id: bool = False
```

- [ ] **Step 4: Pass local_id from the engine**

In `src/bapp_connectors/core/sync/engine.py`, replace line 271:

```python
            created = adapter.create_category(name=category.name, parent_id=remote_parent_id)
```

with:

```python
            if adapter.accepts_local_category_id:
                created = adapter.create_category(name=category.name, parent_id=remote_parent_id, local_id=category.category_id)
            else:
                created = adapter.create_category(name=category.name, parent_id=remote_parent_id)
```

- [ ] **Step 5: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/core/test_engine_category_local_id.py tests/core/test_sync_engine.py -v
```

Expected: all pass (3 new tests plus the existing engine suite; the existing `_MockFullAdapter` at `tests/core/test_sync_engine.py:27-92` keeps the two-argument `create_category` and is still called without `local_id`).

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/core/capabilities/product_management.py src/bapp_connectors/core/sync/engine.py tests/core/test_engine_category_local_id.py
git commit -m "feat(core): sync_categories passes local_id to adapters that accept it"
```

---

### Task 5: ShopPort.sideloads_images

**Files**
- Modify: `src/bapp_connectors/core/ports/shop.py:19-27` (class attributes of `ShopPort`)
- Test: `tests/core/test_shop_port_since.py` (append one test)

**Interfaces**
- Produces: class attribute `ShopPort.sideloads_images: bool = True`. Adapters that only store image URLs set it to False; `BappStoreShopAdapter.sideloads_images = False` (Task 13). Consumers may relax image batch caps when it is False. `ShopPort.supports_modified_since: bool = False` stays where it is (`shop.py:21`, already asserted by `tests/core/test_shop_port_since.py`).

- [ ] **Step 1: Write the failing test.** Append to `tests/core/test_shop_port_since.py`:

```python


def test_shop_port_sideloads_images_by_default():
    assert ShopPort.sideloads_images is True
```

- [ ] **Step 2: Run the test, confirm it fails**

```
uv run --extra dev pytest tests/core/test_shop_port_since.py -v
```

Expected: `test_shop_port_sideloads_images_by_default` fails with `AttributeError: type object 'ShopPort' has no attribute 'sideloads_images'`; the two existing tests pass.

- [ ] **Step 3: Add the attribute**

In `src/bapp_connectors/core/ports/shop.py`, replace lines 19-27:

```python
class ShopPort(BasePort):
    #: True when get_products honours `since` (server-side "modified after" filter).
    supports_modified_since: bool = False

    """
    Common contract for all shop/marketplace adapters.

    Covers: orders, products, stock/price sync.
    """
```

with:

```python
class ShopPort(BasePort):
    """
    Common contract for all shop/marketplace adapters.

    Covers: orders, products, stock/price sync.
    """

    #: True when get_products honours `since` (server-side "modified after" filter).
    supports_modified_since: bool = False

    #: True when the provider downloads product images itself on upload; False when it stores URLs only.
    sideloads_images: bool = True
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/core/test_shop_port_since.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/core/ports/shop.py tests/core/test_shop_port_since.py
git commit -m "feat(core): ShopPort.sideloads_images flag"
```

---

### Task 6: Provider manifest

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/__init__.py` (docstring only; Task 16 replaces it with the registration)
- Create: `src/bapp_connectors/providers/shop/bapp_store/manifest.py`
- Test: `tests/shop/bapp_store/test_manifest.py`

`tests/shop/bapp_store/__init__.py` already exists from Task 1; do not re-create it.

**Interfaces**
- Consumes: `VolumePricingCapability` (Task 3); `BulkUpsertCapability`, `CategoryManagementCapability`, `ProductCreationCapability`, `ProductFullUpdateCapability`, `ProductLookupCapability`, `WebhookCapability` from `bapp_connectors.core.capabilities` (imported the same way at `src/bapp_connectors/providers/shop/woocommerce/manifest.py:5-17`); `ShopPort` from `bapp_connectors.core.ports`; `ProviderManifest`, `AuthConfig`, `CredentialField`, `SettingsConfig`, `SettingsField`, `RateLimitConfig`, `RetryConfig`, `WebhookConfig` from `bapp_connectors.core.manifest`; `AuthStrategy`, `FieldType`, `ProviderFamily` from `bapp_connectors.core.types`.
- Produces: module-level `manifest: ProviderManifest` with `name="bapp_store"`, `display_name="Company Store (BAPP)"`, credentials `store_url` (role `endpoint`) and `token` (sensitive), and the six settings fields listed in Global Constraints. Task 13 sets `manifest = manifest` on `BappStoreShopAdapter`; Task 16 registers it.
- Only `vat_rate` is read by the adapter (Task 13). The other five keys exist so the consumer (aio-backend `SyncConfig.from_connection`) can persist them on the connection; the adapter deliberately ignores them, and `batch_size` is enforced adapter-side as the fixed ceiling `max_batch_size = 100` because the store rejects larger batches with 413 regardless of the setting.

- [ ] **Step 1: Write the failing test** at `tests/shop/bapp_store/test_manifest.py`:

```python
from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, ProviderFamily
from bapp_connectors.providers.shop.bapp_store.manifest import manifest


def test_identity():
    assert manifest.name == "bapp_store"
    assert manifest.family == ProviderFamily.SHOP
    assert manifest.display_name == "Company Store (BAPP)"
    assert manifest.allow_multiple is True
    assert manifest.validate() == []


def test_credentials():
    assert manifest.auth.strategy == AuthStrategy.CUSTOM
    fields = {f.name: f for f in manifest.auth.required_fields}
    assert fields["store_url"].role == "endpoint" and fields["store_url"].sensitive is False
    assert fields["token"].sensitive is True
    assert manifest.auth.validate_credentials({}) == ["store_url", "token"]
    assert manifest.auth.validate_credentials({"store_url": "https://x-st.sites.bapp.ro", "token": "t"}) == []


def test_settings_have_store_defaults():
    defaults = manifest.settings.apply_defaults({})
    assert defaults["prices_include_vat"] is True
    assert defaults["vat_rate"] == "0.21"
    assert defaults["batch_size"] == 100
    assert defaults["pause_seconds"] == 1
    assert defaults["publish_status"] == "publish"
    assert defaults["sync_images"] is True


def test_publish_status_choices_are_validated():
    assert manifest.settings.validate_settings({"publish_status": "pending"}) != []
    assert manifest.settings.validate_settings({"publish_status": "draft"}) == []


def test_capabilities():
    assert set(manifest.capabilities) == {
        ShopPort,
        BulkUpsertCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        ProductLookupCapability,
        CategoryManagementCapability,
        VolumePricingCapability,
        WebhookCapability,
    }


def test_webhooks_and_limits():
    assert manifest.webhooks.supported is True
    assert manifest.webhooks.signature_method == "hmac-sha256"
    assert manifest.webhooks.signature_header == "X-BappStore-Signature"
    assert manifest.webhooks.events == ["order.created", "order.updated"]
    assert manifest.rate_limit.requests_per_second == 10
    assert manifest.retry.max_retries == 3
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_manifest.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store'`.

- [ ] **Step 3: Write the package docstring and the manifest**

`src/bapp_connectors/providers/shop/bapp_store/__init__.py`:

```python
"""Company Store (BAPP) shop provider."""
```

`src/bapp_connectors/providers/shop/bapp_store/manifest.py`:

```python
"""
Company Store provider manifest: capabilities, credentials, settings, rate limits, webhook config.
"""

from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    SettingsConfig,
    SettingsField,
    WebhookConfig,
)
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.core.types import AuthStrategy, FieldType, ProviderFamily

manifest = ProviderManifest(
    name="bapp_store",
    family=ProviderFamily.SHOP,
    allow_multiple=True,
    display_name="Company Store (BAPP)",
    description="BAPP Company Store storefront: catalog push with volume pricing, order pull, order webhooks.",
    base_url="https://placeholder.local/api/",  # replaced by the store_url credential in the client
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="store_url", label="Store URL", sensitive=False, help_text="Internal store host, e.g. https://acme-st.sites.bapp.ro", role="endpoint"),
            CredentialField(name="token", label="Sync Token", sensitive=True, help_text="Store API token scoped to the sync app"),
        ],
    ),
    settings=SettingsConfig(
        fields=[
            SettingsField(name="prices_include_vat", label="Store Prices Include VAT", field_type=FieldType.BOOL, default=True, help_text="Company Store displays gross prices; leave on unless the store is configured net."),
            SettingsField(name="vat_rate", label="VAT Rate", field_type=FieldType.STR, default="0.21", help_text="VAT rate as a decimal (0.21 for 21%). Used to convert between net and gross prices."),
            SettingsField(name="batch_size", label="Products per batch", field_type=FieldType.INT, default=100, help_text="Products per CatalogSyncTask call (the store accepts at most 100)."),
            SettingsField(name="pause_seconds", label="Pause between batches (s)", field_type=FieldType.INT, default=1, help_text="Seconds to wait between consecutive batches."),
            SettingsField(name="publish_status", label="Status for new products", field_type=FieldType.SELECT, choices=["publish", "draft"], default="publish", help_text="New products are visible immediately or created inactive for review."),
            SettingsField(name="sync_images", label="Sync product images", field_type=FieldType.BOOL, default=True, help_text="Send photo URLs to the store (the store stores URLs, it does not download them)."),
        ],
    ),
    capabilities=[
        ShopPort,
        BulkUpsertCapability,
        ProductCreationCapability,
        ProductFullUpdateCapability,
        ProductLookupCapability,
        CategoryManagementCapability,
        VolumePricingCapability,
        WebhookCapability,
    ],
    rate_limit=RateLimitConfig(requests_per_second=10, burst=10),
    retry=RetryConfig(),
    webhooks=WebhookConfig(
        supported=True,
        signature_method="hmac-sha256",
        signature_header="X-BappStore-Signature",
        events=["order.created", "order.updated"],
    ),
)
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_manifest.py -v
```

Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/__init__.py src/bapp_connectors/providers/shop/bapp_store/manifest.py tests/shop/bapp_store/test_manifest.py
git commit -m "feat(bapp_store): provider manifest"
```

---

### Task 7: Error mapping

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/errors.py`
- Create: `tests/shop/bapp_store/fake_response.py`
- Test: `tests/shop/bapp_store/test_errors_unit.py`

**Interfaces**
- Consumes: `AuthenticationError` (`src/bapp_connectors/core/errors.py:24`), `ProviderError` (`:53`), `PermanentProviderError` (`:64`), `ConnectorError` (`:11`); all accept extra keyword arguments and set them as attributes.
- Produces: `map_error(status: int, body: str) -> ConnectorError` (returns, never raises); `raise_for_status(response) -> None` where `response` exposes `.ok`, `.status_code`, `.text`. Also `FakeResponse(status_code=200, payload=None, text="")` in `tests/shop/bapp_store/fake_response.py`, with `.ok` and `.json()`, reused by Tasks 9, 13 and 14 to can `direct_response=True` calls.

- [ ] **Step 1: Write the failing test** at `tests/shop/bapp_store/test_errors_unit.py`:

```python
import pytest

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError
from bapp_connectors.providers.shop.bapp_store.errors import map_error, raise_for_status
from tests.shop.bapp_store.fake_response import FakeResponse


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses_map_to_authentication_error(status):
    err = map_error(status, '{"detail": "bad token"}')
    assert isinstance(err, AuthenticationError)
    assert err.retryable is False
    assert err.status_code == status
    assert "bad token" in str(err)


@pytest.mark.parametrize("status", [400, 404, 413])
def test_other_4xx_is_permanent(status):
    err = map_error(status, "too large")
    assert isinstance(err, PermanentProviderError)
    assert err.retryable is False and err.status_code == status


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retryable(status):
    err = map_error(status, "boom")
    assert isinstance(err, ProviderError)
    assert err.retryable is True and err.status_code == status


def test_body_is_truncated():
    assert len(str(map_error(500, "x" * 2000))) < 600


def test_raise_for_status_passes_2xx_and_raises_errors():
    raise_for_status(FakeResponse(status_code=200, payload={}))
    with pytest.raises(PermanentProviderError):
        raise_for_status(FakeResponse(status_code=413, text="over 100 products"))
```

And `tests/shop/bapp_store/fake_response.py`:

```python
"""Minimal requests.Response stand-in for calls made with direct_response=True."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FakeResponse:
    status_code: int = 200
    payload: Any = None
    text: str = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self.payload
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_errors_unit.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store.errors'`.

- [ ] **Step 3: Write the module** at `src/bapp_connectors/providers/shop/bapp_store/errors.py`:

```python
"""
Company Store error mapping: HTTP status -> framework error.
"""

from __future__ import annotations

from bapp_connectors.core.errors import AuthenticationError, ConnectorError, PermanentProviderError, ProviderError


def map_error(status: int, body: str) -> ConnectorError:
    detail = body[:500]
    if status in (401, 403):
        return AuthenticationError(f"Company Store rejected the sync token: {status} {detail}", status_code=status)
    if 400 <= status < 500:
        return PermanentProviderError(f"Company Store client error {status}: {detail}", status_code=status)
    return ProviderError(f"Company Store server error {status}: {detail}", status_code=status, retryable=True)


def raise_for_status(response) -> None:
    if response.ok:
        return
    raise map_error(response.status_code, response.text)
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_errors_unit.py -v
```

Expected: `10 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/errors.py tests/shop/bapp_store/test_errors_unit.py tests/shop/bapp_store/fake_response.py
git commit -m "feat(bapp_store): map store HTTP errors to framework errors"
```

---

### Task 8: Raw payload models

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/models.py`
- Test: `tests/shop/bapp_store/test_client_unit.py` (new; Task 9 appends the client section)

**Interfaces**
- Consumes: `pydantic.BaseModel`, `pydantic.Field`.
- Produces: `SyncItemResult(index: int, id: str, status: str, error: str = "", code: str = "")` and `SyncTaskResponse(categories: list[SyncItemResult] = [], products: list[SyncItemResult] = [], rules_applied: bool = False, webhook_applied: bool = False)`. Task 11's `bulk_result_from_response` parses raw dicts with `SyncTaskResponse.model_validate(response)`; Task 13's adapter uses it for category and rules results.

- [ ] **Step 1: Write the failing test** at `tests/shop/bapp_store/test_client_unit.py`:

```python
from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse


def test_sync_task_response_parses_positional_results():
    parsed = SyncTaskResponse.model_validate(
        {
            "categories": [{"index": 0, "id": "12", "status": "created", "error": "", "code": ""}],
            "products": [
                {"index": 0, "id": "501", "status": "updated"},
                {"index": 1, "id": "502", "status": "error", "error": "unknown category 99", "code": "unknown_category"},
            ],
            "rules_applied": True,
        }
    )
    assert parsed.categories == [SyncItemResult(index=0, id="12", status="created")]
    assert parsed.products[1].code == "unknown_category"
    assert parsed.rules_applied is True and parsed.webhook_applied is False


def test_sync_task_response_defaults_to_empty():
    assert SyncTaskResponse.model_validate({}) == SyncTaskResponse()
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_client_unit.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store.models'`.

- [ ] **Step 3: Write the module** at `src/bapp_connectors/providers/shop/bapp_store/models.py`:

```python
"""
Raw Company Store API payload shapes. Not DTOs: conversion happens in mappers.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SyncItemResult(BaseModel):
    """One positional entry of a CatalogSyncTask response (status: created | updated | error)."""

    index: int
    id: str
    status: str
    error: str = ""
    code: str = ""


class SyncTaskResponse(BaseModel):
    categories: list[SyncItemResult] = Field(default_factory=list)
    products: list[SyncItemResult] = Field(default_factory=list)
    rules_applied: bool = False
    webhook_applied: bool = False
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_client_unit.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/models.py tests/shop/bapp_store/test_client_unit.py
git commit -m "feat(bapp_store): CatalogSyncTask response models"
```

---

### Task 9: HTTP client

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/client.py`
- Modify: `tests/shop/bapp_store/test_client_unit.py` (append the client section)

**Interfaces**
- Consumes: `ResilientHttpClient` (`bapp_connectors.core.http`, class at `src/bapp_connectors/core/http/client.py:33`, whose `call(method, path, direct_response=False, headers=None, retry=True, **kwargs)` at `:176-202` classifies non-2xx into framework errors unless `direct_response=True`, and whose `base_url` is a plain attribute at `:50` that absolute paths bypass at `:59-63`); `NoAuth` (`src/bapp_connectors/core/http/auth.py:27`); `ConnectorError`; `raise_for_status` (Task 7); `FakeHttpClient` (`tests/fake_http.py:25`); `FakeResponse` (Task 7).
- Produces: `BappStoreClient(store_url: str, token: str, http_client=None)` with attributes `base_url` and `http`, class attribute `SYNC_TIMEOUT`, and methods `test_auth() -> bool`, `sync_task(payload: dict) -> dict`, `list_categories() -> list[dict]`, `find_products(code: str | None = None, page: int = 1) -> dict`, `export_orders(since: str | None, cursor: str | None, limit: int = 50) -> dict`, `export_order(number: str) -> dict`, `set_webhook(url: str, secret_token: str) -> dict`. Module constants `CATEGORY_PATH`, `PRODUCT_PATH`, `SYNC_TASK_PATH`, `ORDERS_EXPORT_PATH`, `ORDER_EXPORT_PATH`, `PAGE_LIMIT`. `sync_task` is the only call made with `direct_response=True` and `retry=False`.
- `_call` is the single place transport failures are classified: `ResilientHttpClient._execute_request` re-raises `requests.RequestException` untouched (`src/bapp_connectors/core/http/client.py:147-157`), and with `retry=False` no retry wrapper sees it either, so a connect or read timeout on a batch would otherwise reach `ProductSyncEngine._push_products_bulk`, which reads `getattr(e, "retryable", False)` (`src/bapp_connectors/core/sync/engine.py:190-195`) and would mark the whole batch non-retryable. `_call` turns every `requests.RequestException` into a retryable `ProviderError`, which is the spec 8 contract (5xx and timeouts retryable).

- [ ] **Step 1: Append the failing tests** to `tests/shop/bapp_store/test_client_unit.py`:

```python
import pytest  # noqa: E402
import requests  # noqa: E402

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError  # noqa: E402
from bapp_connectors.providers.shop.bapp_store.client import (  # noqa: E402
    CATEGORY_PATH,
    ORDER_EXPORT_PATH,
    ORDERS_EXPORT_PATH,
    PRODUCT_PATH,
    SYNC_TASK_PATH,
    BappStoreClient,
)
from tests.fake_http import FakeHttpClient  # noqa: E402
from tests.shop.bapp_store.fake_response import FakeResponse  # noqa: E402

STORE = "https://acme-st.sites.bapp.ro/"
HEADERS = {"Authorization": "Token s3cret", "X-App-Slug": "sync"}


@pytest.fixture
def http():
    return FakeHttpClient()


@pytest.fixture
def client(http):
    return BappStoreClient(STORE, "s3cret", http_client=http)


def test_base_url_and_headers(client, http):
    assert client.base_url == "https://acme-st.sites.bapp.ro/api/"
    assert http.base_url == client.base_url
    http.add("GET", CATEGORY_PATH, {"count": 0, "next": None, "previous": None, "results": []})
    client.test_auth()
    assert http.last_call().kwargs["headers"] == HEADERS


def test_builds_its_own_http_client_when_none_given():
    client = BappStoreClient("https://acme-st.sites.bapp.ro", "s3cret")
    assert client.http.base_url == "https://acme-st.sites.bapp.ro/api/"
    assert client.http.provider_name == "bapp_store"


def test_test_auth(client, http):
    http.add("GET", CATEGORY_PATH, {"count": 0, "next": None, "previous": None, "results": []})
    assert client.test_auth() is True
    assert http.last_call().kwargs["params"] == {"page_size": 1}

    def reject(method, path, kwargs):
        raise AuthenticationError("401", status_code=401)

    http.responses.clear()
    http.add("GET", CATEGORY_PATH, reject)
    assert client.test_auth() is False


def test_sync_task_posts_payload_without_retry(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(200, {"products": [], "categories": [], "rules_applied": False, "webhook_applied": False}))
    result = client.sync_task({"products": [{"id": "1"}]})
    assert result["rules_applied"] is False
    call = http.last_call()
    assert call.method == "POST" and call.path == SYNC_TASK_PATH
    assert call.kwargs["json"] == {"products": [{"id": "1"}]}
    # FakeHttpClient.call takes direct_response as a named parameter, so it is not in the recorded kwargs.
    assert call.kwargs["retry"] is False
    assert call.kwargs["timeout"] == BappStoreClient.SYNC_TIMEOUT


def test_sync_task_maps_error_status(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(413, text="over 100 products"))
    with pytest.raises(PermanentProviderError, match="over 100 products"):
        client.sync_task({"products": []})


def test_transport_failure_is_a_retryable_provider_error(client, http):
    def time_out(method, path, kwargs):
        raise requests.ReadTimeout("read timed out")

    http.add("POST", SYNC_TASK_PATH, time_out)
    with pytest.raises(ProviderError) as excinfo:
        client.sync_task({"products": []})
    assert excinfo.value.retryable is True


def test_list_categories_follows_next_pages(client, http):
    first = {"count": 3, "next": STORE + "api/" + CATEGORY_PATH + "?page=2&page_size=100", "previous": None, "results": [{"id": 1}, {"id": 2}]}
    second = {"count": 3, "next": None, "previous": "x", "results": [{"id": 3}]}
    pages = iter([first, second])
    http.add("GET", CATEGORY_PATH, lambda method, path, kwargs: next(pages))
    assert client.list_categories() == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert http.calls[0].kwargs["params"] == {"page_size": 100}
    assert http.calls[1].path == first["next"]


def test_find_products_by_code_and_page(client, http):
    http.add("GET", PRODUCT_PATH, {"count": 1, "next": None, "previous": None, "results": [{"code": "SKU-1"}]})
    assert client.find_products(code="SKU-1")["results"] == [{"code": "SKU-1"}]
    assert http.last_call().kwargs["params"] == {"page_size": 100, "page": 1, "code": "SKU-1"}
    client.find_products(page=3)
    assert http.last_call().kwargs["params"] == {"page_size": 100, "page": 3}


def test_export_orders_omits_empty_filters(client, http):
    http.add("GET", ORDERS_EXPORT_PATH, {"results": [], "next_cursor": None})
    client.export_orders(since=None, cursor=None)
    assert http.last_call().kwargs["params"] == {"limit": 50}
    client.export_orders(since="2026-09-01T00:00:00Z", cursor="ORD-000123", limit=10)
    assert http.last_call().kwargs["params"] == {"limit": 10, "since": "2026-09-01T00:00:00Z", "cursor": "ORD-000123"}


def test_export_order_by_number(client, http):
    http.add("GET", ORDER_EXPORT_PATH, {"number": "ORD-000123"})
    assert client.export_order("ORD-000123") == {"number": "ORD-000123"}
    assert http.last_call().kwargs["params"] == {"number": "ORD-000123"}


def test_set_webhook_is_a_sync_task(client, http):
    http.add("POST", SYNC_TASK_PATH, FakeResponse(200, {"webhook_applied": True}))
    assert client.set_webhook("https://panel.bapp.ro/api/webhooks/1/2/order.created/", "abc")["webhook_applied"] is True
    assert http.last_call().kwargs["json"] == {"webhook": {"url": "https://panel.bapp.ro/api/webhooks/1/2/order.created/", "secret": "abc"}}
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_client_unit.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store.client'`.

- [ ] **Step 3: Write the client** at `src/bapp_connectors/providers/shop/bapp_store/client.py`:

```python
"""
Company Store API client: raw HTTP calls against the store's /api/ surface, no business logic.
"""

from __future__ import annotations

from typing import Any

import requests

from bapp_connectors.core.errors import ConnectorError, ProviderError
from bapp_connectors.core.http import ResilientHttpClient
from bapp_connectors.core.http.auth import NoAuth
from bapp_connectors.providers.shop.bapp_store.errors import raise_for_status

CATEGORY_PATH = "content-type/store.storecategory/"
PRODUCT_PATH = "content-type/store.storeproduct/"
SYNC_TASK_PATH = "tasks/store.CatalogSyncTask"
ORDERS_EXPORT_PATH = "tasks/store.OrdersExportTask"
ORDER_EXPORT_PATH = "tasks/store.OrderExportTask"
PAGE_LIMIT = 100


class BappStoreClient:
    # One batch is one store transaction: long read timeout, never replayed by the retry wrapper.
    SYNC_TIMEOUT = (10, 300)

    def __init__(self, store_url: str, token: str, http_client=None):
        self.base_url = store_url.rstrip("/") + "/api/"
        # Explicit headers on every call: the registry-built client carries NoAuth for CUSTOM.
        self._headers = {"Authorization": f"Token {token}", "X-App-Slug": "sync"}
        self.http = http_client or ResilientHttpClient(base_url=self.base_url, auth=NoAuth(), provider_name="bapp_store")
        self.http.base_url = self.base_url

    def _call(self, method: str, path: str, **kwargs):
        try:
            return self.http.call(method, path, headers=self._headers, **kwargs)
        except requests.RequestException as exc:
            # A transport failure is no verdict from the store, so the caller must be free to retry it.
            raise ProviderError(f"Company Store request failed: {exc}", retryable=True) from exc

    def test_auth(self) -> bool:
        try:
            self._call("GET", CATEGORY_PATH, params={"page_size": 1})
        except ConnectorError:
            return False
        return True

    def sync_task(self, payload: dict) -> dict:
        response = self._call("POST", SYNC_TASK_PATH, json=payload, direct_response=True, retry=False, timeout=self.SYNC_TIMEOUT)
        raise_for_status(response)
        return response.json()

    def list_categories(self) -> list[dict]:
        page = self._call("GET", CATEGORY_PATH, params={"page_size": PAGE_LIMIT})
        rows = list(page["results"])
        while page.get("next"):
            page = self._call("GET", page["next"])
            rows.extend(page["results"])
        return rows

    def find_products(self, code: str | None = None, page: int = 1) -> dict:
        params: dict[str, Any] = {"page_size": PAGE_LIMIT, "page": page}
        if code:
            params["code"] = code
        return self._call("GET", PRODUCT_PATH, params=params)

    def export_orders(self, since: str | None, cursor: str | None, limit: int = 50) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if since:
            params["since"] = since
        if cursor:
            params["cursor"] = cursor
        return self._call("GET", ORDERS_EXPORT_PATH, params=params)

    def export_order(self, number: str) -> dict:
        return self._call("GET", ORDER_EXPORT_PATH, params={"number": number})

    def set_webhook(self, url: str, secret_token: str) -> dict:
        return self.sync_task({"webhook": {"url": url, "secret": secret_token}})
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_client_unit.py -v
```

Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/client.py tests/shop/bapp_store/test_client_unit.py
git commit -m "feat(bapp_store): store API client"
```

---

### Task 10: Outbound mappers (product, update, category records, html_to_text)

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/mappers.py`
- Create: `tests/shop/bapp_store/test_mappers_unit.py`

**Interfaces**
- Consumes: `Product` (`src/bapp_connectors/core/dto/product.py:98`), `ProductUpdate` (`:120`), `ProductPhoto` (`:21`); `to_gross` (`src/bapp_connectors/core/pricing.py:22`); the `fixtures/products_batch.json` file from Task 1.
- Produces: `html_to_text(html: str) -> str`; `product_to_record(product: Product, vat_rate: Decimal = Decimal("0.21")) -> dict`; `update_to_record(update: ProductUpdate, vat_rate: Decimal = Decimal("0.21")) -> dict`; `category_record(name: str, parent_id: str | None, local_id: str, is_active: bool | None = True) -> dict`, where `is_active=None` omits the key entirely (what `update_category` sends, spec 2.2); module constant `DEFAULT_VAT_RATE`. `vat_rate` is an optional trailing keyword, so one-argument calls still work. Record shape: `record["price"]["amount"]` is `extra["bapp"]["gross_price"]` when present, else `str(to_gross(dto.price, vat_rate))`; `extra["price_tiers"]` entries `{min_quantity, price}` become `record["price_tiers"]` entries `{min_quantity, price_amount}`.

- [ ] **Step 1: Write the failing tests** at `tests/shop/bapp_store/test_mappers_unit.py`:

```python
"""bapp_store mapper tests: outbound records must equal the cross-repo fixture samples."""
from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.providers.shop.bapp_store.mappers import (
    category_record,
    html_to_text,
    product_to_record,
    update_to_record,
)

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"


@pytest.fixture(scope="module")
def batch() -> dict:
    return json.loads((FIXTURES / "products_batch.json").read_text())


def _product_from_fixture(record: dict) -> Product:
    """Rebuild the DTO a panel-side consumer would hand the adapter for this fixture record."""
    extra = {
        "bapp": record["extra"]["bapp"],
        "price_tiers": [{"min_quantity": t["min_quantity"], "price": t["price_amount"]} for t in record["price_tiers"]],
    }
    return Product(
        product_id=record["id"],
        sku=record["code"],
        barcode=record["code_ean"] or None,
        name=record["name"],
        description=record["description"],
        price=Decimal("95.00"),  # net PriceCodec value, irrelevant once extra["bapp"] is present
        currency="RON",
        stock=int(record["stock"]),
        active=record["is_active"],
        category_ids=list(record["category_ids"]),
        photos=[ProductPhoto(url=p["url"], position=p["order"]) for p in record.get("photos", [])],
        extra=extra,
    )


@pytest.mark.parametrize("index", [0, 1, 2])
def test_product_to_record_matches_fixture(batch, index):
    expected = batch["request"]["products"][index]
    assert product_to_record(_product_from_fixture(expected)) == expected


def test_product_without_bapp_block_falls_back_to_gross_of_net_price():
    product = Product(product_id="9", name="X", sku="X-1", price=Decimal("100.00"), stock=None)
    record = product_to_record(product, vat_rate=Decimal("0.21"))
    assert record["price"] == {"amount": "121.00", "currency": "RON"}
    assert record["stock"] == "0"
    assert record["extra"] == {}
    assert record["price_tiers"] == []
    assert "photos" not in record
    assert record["primary_category"] is None


def test_product_without_price_omits_price_key():
    record = product_to_record(Product(product_id="9", name="X"))
    assert "price" not in record


def test_update_to_record_full_matches_fixture(batch):
    expected = batch["request"]["products"][0]
    source = _product_from_fixture(expected)
    update = ProductUpdate(
        product_id=source.product_id, sku=source.sku, barcode=source.barcode, name=source.name,
        description=source.description, price=source.price, currency=source.currency, stock=source.stock,
        active=source.active, category_ids=source.category_ids, photos=source.photos, extra=source.extra,
    )
    assert update_to_record(update) == expected


def test_update_to_record_partial_sends_only_set_fields():
    update = ProductUpdate(product_id="345100", stock=3, active=False)
    assert update_to_record(update) == {"id": "345100", "stock": "3", "is_active": False}


def test_update_to_record_empty_tiers_clear_and_empty_categories_clear_primary():
    update = ProductUpdate(product_id="1", category_ids=[], extra={"price_tiers": []})
    record = update_to_record(update)
    assert record["price_tiers"] == []
    assert record["category_ids"] == []
    assert record["primary_category"] is None


def test_update_price_without_bapp_uses_vat_rate():
    record = update_to_record(ProductUpdate(product_id="1", price=Decimal("10.00")), vat_rate=Decimal("0.19"))
    assert record["price"] == {"amount": "11.90", "currency": "RON"}


def test_category_record_matches_fixture(batch):
    expected = batch["request"]["categories"]
    assert category_record("Scule", None, "159") == expected[0]
    assert category_record("Burghie", "159", "160") == expected[1]
    assert category_record("Burghie", "159", "160", is_active=None) == {"id": "160", "parent_id": "159", "name": "Burghie"}


def test_html_to_text_strips_tags_and_keeps_block_breaks():
    html = "<p>Ciocan <b>cu</b> coada.</p><p>Al doilea &amp; ultimul</p>"
    assert html_to_text(html) == "Ciocan cu coada.\nAl doilea & ultimul"


def test_html_to_text_plain_text_passes_through():
    assert html_to_text("Ciocan cu coada de lemn.") == "Ciocan cu coada de lemn."
    assert html_to_text("") == ""
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
uv run --extra dev pytest tests/shop/bapp_store/test_mappers_unit.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store.mappers'`.

- [ ] **Step 3: Write the mappers** at `src/bapp_connectors/providers/shop/bapp_store/mappers.py`:

```python
"""
Company Store <-> DTO mappers.

Outbound records follow the CatalogSyncTask contract (fixtures/products_batch.json);
inbound rows come from the store's public content-type viewsets.
"""

from __future__ import annotations

from decimal import Decimal
from html.parser import HTMLParser

from bapp_connectors.core.dto import Product, ProductPhoto, ProductUpdate
from bapp_connectors.core.pricing import to_gross

DEFAULT_VAT_RATE = Decimal("0.21")

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip markup to plain text; block elements become line breaks."""
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    return "\n".join(line for line in lines if line)


def _price_amount(net_price: Decimal | None, bapp: dict, vat_rate: Decimal) -> str | None:
    if bapp.get("gross_price") is not None:
        return str(bapp["gross_price"])
    if net_price is None:
        return None
    return str(to_gross(net_price, vat_rate))


def _tiers(extra: dict) -> list[dict]:
    return [{"min_quantity": str(t["min_quantity"]), "price_amount": str(t["price"])} for t in extra.get("price_tiers", [])]


def _photos(photos: list[ProductPhoto]) -> list[dict]:
    return [{"url": p.url, "order": p.position} for p in photos]


def product_to_record(product: Product, vat_rate: Decimal = DEFAULT_VAT_RATE) -> dict:
    """Map a Product DTO to one CatalogSyncTask product record (create or full replace)."""
    bapp = dict(product.extra.get("bapp") or {})
    record: dict = {
        "id": product.product_id,
        "name": product.name,
        "code": product.sku or "",
        "code_ean": product.barcode or "",
        "unit": bapp.get("unit", "buc"),
        "description": html_to_text(product.description),
        "stock": str(product.stock if product.stock is not None else 0),
        "is_active": product.active,
        "category_ids": list(product.category_ids),
        "primary_category": product.category_ids[0] if product.category_ids else None,
        "price_tiers": _tiers(product.extra),
        "extra": {"bapp": bapp} if bapp else {},
    }
    amount = _price_amount(product.price, bapp, vat_rate)
    if amount is not None:
        record["price"] = {"amount": amount, "currency": product.currency or "RON"}
    if product.photos:
        record["photos"] = _photos(product.photos)
    return record


def update_to_record(update: ProductUpdate, vat_rate: Decimal = DEFAULT_VAT_RATE) -> dict:
    """Map a ProductUpdate to a partial record; absent keys keep their store values."""
    bapp = dict(update.extra.get("bapp") or {})
    record: dict = {"id": update.product_id}
    if update.name is not None:
        record["name"] = update.name
    if update.sku is not None:
        record["code"] = update.sku
    if update.barcode is not None:
        record["code_ean"] = update.barcode
    if update.description is not None:
        record["description"] = html_to_text(update.description)
    amount = _price_amount(update.price, bapp, vat_rate)
    if amount is not None:
        record["price"] = {"amount": amount, "currency": update.currency or "RON"}
    if update.stock is not None:
        record["stock"] = str(update.stock)
    if update.active is not None:
        record["is_active"] = update.active
    if update.category_ids is not None:
        record["category_ids"] = list(update.category_ids)
        record["primary_category"] = update.category_ids[0] if update.category_ids else None
    if update.photos is not None:
        record["photos"] = _photos(update.photos)
    if "price_tiers" in update.extra:
        record["price_tiers"] = _tiers(update.extra)
    if bapp:
        record["extra"] = {"bapp": bapp}
        if "unit" in bapp:
            record["unit"] = bapp["unit"]
    return record


def category_record(name: str, parent_id: str | None, local_id: str, is_active: bool | None = True) -> dict:
    """One CatalogSyncTask category record keyed by the BAPP category id."""
    record: dict = {"id": local_id, "parent_id": parent_id, "name": name}
    # None omits the key: an update carries name and parent only, so a store-side toggle survives it.
    if is_active is not None:
        record["is_active"] = is_active
    return record
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_mappers_unit.py -v
```

Expected: `12 passed`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/mappers.py tests/shop/bapp_store/test_mappers_unit.py
git commit -m "feat(bapp_store): outbound product, update and category record mappers"
```

---

### Task 11: Rules body, positional bulk result, inbound category and product rows

**Files**
- Modify: `src/bapp_connectors/providers/shop/bapp_store/mappers.py` (replace the import block, append after `category_record`)
- Modify: `tests/shop/bapp_store/test_mappers_unit.py` (append)

**Interfaces**
- Consumes: `ShopRules`, `OrderValueTier` (Task 2); `SyncTaskResponse`, `SyncItemResult` (Task 8); `BulkItemResult` and `BulkUpsertResult` (`src/bapp_connectors/core/dto/base.py:60-86`); `ProductCategory` (`src/bapp_connectors/core/dto/product.py:12`); `to_net` (`src/bapp_connectors/core/pricing.py:36`); the `fixtures/rules.json` file from Task 1.
- Produces:
  - `rules_to_body(rules: ShopRules) -> dict`, computing `policy_hash` per the `policy_hash_recipe` in `rules.json` and then merging `rules.extra`.
  - `bulk_result_from_response(response: dict, n_creates: int, n_updates: int, create_ids: list[str], update_ids: list[str]) -> BulkUpsertResult`. The store answers positionally: the first `n_creates` product entries belong to the creates, the rest to the updates.
  - `category_from_store(row: dict) -> ProductCategory`: `category_id` is the store `external_id`, `extra["store_id"]` is the store pk, `parent_id` is the parent's `external_id` when the row expands the parent and otherwise the parent's store pk (Task 13's `get_categories` remaps it).
  - `product_from_store(row: dict, vat_rate: Decimal) -> Product`: `product_id` is `external_id`, price is net, `extra` carries `gross_price` and `store_id`.

- [ ] **Step 1: Append the failing tests** to `tests/shop/bapp_store/test_mappers_unit.py`:

```python

from bapp_connectors.core.dto import OrderValueTier, ShopRules  # noqa: E402
from bapp_connectors.providers.shop.bapp_store.mappers import (  # noqa: E402
    bulk_result_from_response,
    category_from_store,
    product_from_store,
    rules_to_body,
)


@pytest.fixture(scope="module")
def rules_fixture() -> dict:
    return json.loads((FIXTURES / "rules.json").read_text())


def test_rules_to_body_matches_fixture_and_computes_policy_hash(rules_fixture):
    rules = ShopRules(
        order_value_tiers=[
            OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00")),
            OrderValueTier(min_total=Decimal("10000.00"), discount_percent=Decimal("5.00")),
        ],
        min_order_total=Decimal("1000.00"),
        currency="RON",
        extra={"connection_id": 123, "synced_at": "2026-09-02T12:00:00+03:00"},
    )
    assert rules_to_body(rules) == rules_fixture["request"]["rules"]


def test_rules_to_body_without_min_total_hashes_null():
    body = rules_to_body(ShopRules(currency="RON"))
    assert body["min_order_total"] is None
    assert body["order_value_tiers"] == []
    assert len(body["policy_hash"]) == 64


def test_bulk_result_splits_positional_products(batch):
    response = dict(batch["response"])
    response["products"] = [
        {"index": 0, "id": "345100", "status": "created", "error": "", "code": ""},
        {"index": 1, "id": "345101", "status": "error", "error": "unknown category 999", "code": "unknown_category"},
        {"index": 2, "id": "345102", "status": "updated", "error": "", "code": ""},
    ]
    result = bulk_result_from_response(response, 2, 1, ["345100", "345101"], ["345102"])
    assert [i.index for i in result.created] == [0, 1]
    assert result.created[0].remote_id == "345100" and result.created[0].ok
    assert result.created[1].error == "unknown category 999"
    assert result.created[1].error_code == "unknown_category"
    assert [i.index for i in result.updated] == [0]
    assert result.updated[0].remote_id == "345102"
    assert result.failed == 1 and result.succeeded == 2


def test_bulk_result_missing_id_falls_back_to_local_id():
    response = {"products": [{"index": 0, "id": "", "status": "error", "error": "bad", "code": "validation"}]}
    result = bulk_result_from_response(response, 1, 0, ["345100"], [])
    assert result.created[0].remote_id == "345100"


def test_category_from_store_with_expanded_parent():
    row = {"id": 7, "external_id": "160", "name": "Burghie", "is_active": True, "parent": {"id": 5, "external_id": "159", "name": "Scule"}}
    cat = category_from_store(row)
    assert cat.category_id == "160" and cat.parent_id == "159" and cat.name == "Burghie"
    assert cat.extra["store_id"] == "7"


def test_category_from_store_with_bare_parent_pk_and_root():
    assert category_from_store({"id": 7, "external_id": "160", "name": "B", "parent": 5}).parent_id == "5"
    assert category_from_store({"id": 5, "external_id": "159", "name": "S", "parent": None}).parent_id is None


def test_product_from_store_converts_gross_to_net():
    row = {
        "id": 11, "external_id": "345100", "code": "CIO-500", "code_ean": "5941234567890", "name": "Ciocan 500 g",
        "description": "Ciocan cu coada de lemn.", "price_amount": "114.9500", "currency": "RON", "stock_qty": "42.0000", "is_active": True,
    }
    product = product_from_store(row, Decimal("0.21"))
    assert product.product_id == "345100" and product.sku == "CIO-500" and product.barcode == "5941234567890"
    assert product.price == Decimal("95.00")
    assert product.stock == 42 and product.active is True and product.currency == "RON"
    assert product.extra == {"store_id": "11", "gross_price": "114.9500"}


def test_product_from_store_blank_code_is_none():
    row = {"id": 1, "external_id": "2", "code": "", "code_ean": "", "name": "N", "price_amount": "0", "stock_qty": "0"}
    product = product_from_store(row, Decimal("0.21"))
    assert product.sku is None and product.barcode is None and product.price == Decimal("0.00")
```

- [ ] **Step 2: Run the tests, confirm they fail**

```
uv run --extra dev pytest tests/shop/bapp_store/test_mappers_unit.py -v
```

Expected: collection error `ImportError: cannot import name 'bulk_result_from_response' from 'bapp_connectors.providers.shop.bapp_store.mappers'`.

- [ ] **Step 3: Replace the import block** at the top of `src/bapp_connectors/providers/shop/bapp_store/mappers.py` (the four lines starting at `from decimal import Decimal`) with:

```python
import hashlib
import json
from decimal import Decimal
from html.parser import HTMLParser

from bapp_connectors.core.dto import (
    BulkItemResult,
    BulkUpsertResult,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
    ShopRules,
)
from bapp_connectors.core.pricing import to_gross, to_net
from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse
```

- [ ] **Step 4: Append the new mappers** after `category_record` in the same file:

```python
def rules_to_body(rules: ShopRules) -> dict:
    """CatalogSyncTask `rules{}` body; the hash covers only the pricing inputs the store re-checks."""
    core = {
        "order_value_tiers": [
            {"min_total": str(t.min_total), "discount_percent": str(t.discount_percent)} for t in rules.order_value_tiers
        ],
        "min_order_total": str(rules.min_order_total) if rules.min_order_total is not None else None,
    }
    policy_hash = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**core, "currency": rules.currency, **rules.extra, "policy_hash": policy_hash}


def _bulk_item(item: SyncItemResult, index: int, local_id: str) -> BulkItemResult:
    return BulkItemResult(index=index, remote_id=item.id or local_id, error=item.error, error_code=item.code)


def bulk_result_from_response(response: dict, n_creates: int, n_updates: int, create_ids: list[str], update_ids: list[str]) -> BulkUpsertResult:
    """Split the task's positional `products[]` back into creates (first n_creates) and updates."""
    parsed = SyncTaskResponse.model_validate(response)
    created: list[BulkItemResult] = []
    updated: list[BulkItemResult] = []
    for item in parsed.products:
        if item.index < n_creates:
            created.append(_bulk_item(item, item.index, create_ids[item.index]))
        elif item.index < n_creates + n_updates:
            offset = item.index - n_creates
            updated.append(_bulk_item(item, offset, update_ids[offset]))
    return BulkUpsertResult(created=created, updated=updated)


def _parent_ref(parent) -> str | None:
    if isinstance(parent, dict):
        return str(parent.get("external_id") or parent.get("id") or "") or None
    return str(parent) if parent else None


def category_from_store(row: dict) -> ProductCategory:
    """Store category row -> DTO keyed by the BAPP id the store holds in `external_id`."""
    return ProductCategory(
        category_id=str(row["external_id"]),
        name=row.get("name", ""),
        parent_id=_parent_ref(row.get("parent")),
        extra={"store_id": str(row["id"]), "is_active": bool(row.get("is_active", True))},
    )


def product_from_store(row: dict, vat_rate: Decimal) -> Product:
    """Store product row -> DTO with the framework's net price."""
    gross = Decimal(str(row.get("price_amount") or "0"))
    return Product(
        product_id=str(row["external_id"]),
        sku=row.get("code") or None,
        barcode=row.get("code_ean") or None,
        name=row.get("name", ""),
        description=row.get("description") or "",
        price=to_net(gross, vat_rate),
        currency=row.get("currency") or "RON",
        stock=int(Decimal(str(row.get("stock_qty") or "0"))),
        active=bool(row.get("is_active", True)),
        extra={"store_id": str(row["id"]), "gross_price": str(gross)},
    )
```

- [ ] **Step 5: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_mappers_unit.py -v
```

Expected: `20 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/mappers.py tests/shop/bapp_store/test_mappers_unit.py
git commit -m "feat(bapp_store): rules body, positional bulk result and inbound row mappers"
```

---

### Task 12: Order mappers

**Files**
- Modify: `src/bapp_connectors/providers/shop/bapp_store/mappers.py` (extend the import block, append at the end of the file)
- Test: `tests/shop/bapp_store/test_orders_unit.py` (new)

**Interfaces**
- Consumes: `Order`, `OrderItem`, `OrderStatus`, `PaymentStatus`, `PaymentType` (`src/bapp_connectors/core/dto/order.py:15-76`); `Contact`, `Address` (`src/bapp_connectors/core/dto/partner.py:10-30`); `PaginatedResult`, `ProviderMeta` (`src/bapp_connectors/core/dto/base.py:15-40`); `to_net` (`src/bapp_connectors/core/pricing.py:36`); the `fixtures/orders_export.json` file from Task 1.
- Produces: `order_from_store(data: dict, vat_rate: Decimal) -> Order`; `orders_page_from_store(data: dict, vat_rate: Decimal) -> PaginatedResult[Order]`; module constants `STORE_ORDER_STATUS_MAP`, `STORE_PAYMENT_STATUS_MAP`, `STORE_PAYMENT_TYPE_MAP`. Task 13's adapter calls both functions.

Mapping contract (spec 4.7): `unit_price` and `total` arrive as gross RON strings; the DTO stores net (`to_net(gross, vat_rate)`) and keeps the gross string in `extra["gross_unit_price"]` (line) and `extra["gross_total"]` (order). `order_id` and `external_id` are both the store order number. The store has no separate shipping contact, so `delivery_address` is the preformatted string and `shipping` / `shipping_address` stay `None`. Billing `reg_com` is not a `Contact` field, so it rides in `Contact.extra`. Unknown status strings fall back to `PENDING` / `UNPAID` / `OTHER` and the raw string is preserved in `raw_status`, `extra["raw_payment_status"]`, `extra["raw_payment_type"]`.

- [ ] **Step 1: Write the failing tests** at `tests/shop/bapp_store/test_orders_unit.py`:

```python
"""Order mapper tests for the bapp_store provider. Pure functions, no network."""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from bapp_connectors.core.dto import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.bapp_store.mappers import order_from_store, orders_page_from_store

FIXTURES = Path("src/bapp_connectors/providers/shop/bapp_store/fixtures")
VAT = Decimal("0.21")


def _export() -> dict:
    return json.loads((FIXTURES / "orders_export.json").read_text())


def test_order_ids_and_status_from_fixture():
    order = order_from_store(_export()["items"][0], VAT)
    assert order.order_id == "ORD-000123"
    assert order.external_id == "ORD-000123"
    assert order.status == OrderStatus.PENDING
    assert order.raw_status == "pending"
    assert order.payment_status == PaymentStatus.UNPAID
    assert order.payment_type == PaymentType.BANK_TRANSFER
    assert order.currency == "RON"
    assert order.created_at == datetime(2026, 9, 2, 14, 5, tzinfo=timezone(timedelta(hours=3)))
    assert order.updated_at == order.created_at
    assert order.external_url == "https://zogjaemtbppsfb0-st.sites.bapp.ro/account/orders/ORD-000123"


def test_order_lines_are_net_with_gross_kept_in_extra():
    order = order_from_store(_export()["items"][0], VAT)
    assert [i.sku for i in order.items] == ["CIO-500", "BAL-60"]
    first, second = order.items
    assert first.product_id == "345100"
    assert first.quantity == Decimal("60")
    assert first.unit_price == Decimal("95.00")
    assert first.currency == "RON"
    assert first.tax_rate == VAT
    assert first.extra["gross_unit_price"] == "114.95"
    assert first.extra["unit_tier"] == "105.75"
    assert first.extra["line_total"] == "6027.75"
    assert second.unit_price == Decimal("66.50")


def test_order_total_is_net_with_gross_and_store_totals_in_extra():
    order = order_from_store(_export()["items"][0], VAT)
    assert order.total == Decimal("8140.56")
    assert order.extra["gross_total"] == "9850.08"
    assert order.extra["goods_total"] == "9850.08"
    assert order.extra["shipping_total"] == "0.00"
    assert order.extra["notes"] == "Livrare dupa ora 10"
    assert order.extra["policy_hash"] == "d781e2f107f3407972917f4a8e84964540086a7f5ad91620de9f4f8536d885b1"
    assert order.extra["volume_discount_total"] == "518.42"
    assert order.extra["value_pct"] == "5.00"


def test_order_billing_contact_carries_company_and_vat_id():
    order = order_from_store(_export()["items"][0], VAT)
    billing = order.billing
    assert billing.name == "Ana Pop"
    assert billing.company_name == "ACME SRL"
    assert billing.vat_id == "RO12345678"
    assert billing.email == "ana@acme.example"
    assert billing.phone == "0712345678"
    assert billing.extra["reg_com"] == "J12/345/2020"
    assert billing.address.street == "Strada Firmei 9"
    assert billing.address.city == "Cluj-Napoca"
    assert billing.address.region == "Cluj"
    assert billing.address.postal_code == "400001"
    assert billing.address.country == "RO"
    assert order.shipping is None
    assert order.shipping_address is None
    assert order.delivery_address == "Strada Firmei 9, Cluj-Napoca, Cluj, 400001"


def test_order_provider_meta_keeps_raw_payload():
    raw = _export()["items"][0]
    order = order_from_store(raw, VAT)
    assert order.provider_meta.provider == "bapp_store"
    assert order.provider_meta.raw_id == "ORD-000123"
    assert order.provider_meta.raw_payload == raw


def test_unknown_status_strings_fall_back_and_are_preserved():
    raw = _export()["items"][0]
    raw = {**raw, "status": "weird", "payment_status": "odd", "payment_type": "voucher"}
    order = order_from_store(raw, VAT)
    assert order.status == OrderStatus.PENDING
    assert order.raw_status == "weird"
    assert order.payment_status == PaymentStatus.UNPAID
    assert order.extra["raw_payment_status"] == "odd"
    assert order.payment_type == PaymentType.OTHER
    assert order.extra["raw_payment_type"] == "voucher"


def test_store_status_aliases():
    raw = _export()["items"][0]
    cases = {
        "confirmed": OrderStatus.ACCEPTED,
        "processing": OrderStatus.PROCESSING,
        "shipped": OrderStatus.SHIPPED,
        "completed": OrderStatus.DELIVERED,
        "delivered": OrderStatus.DELIVERED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "returned": OrderStatus.RETURNED,
        "refunded": OrderStatus.REFUNDED,
    }
    for store_status, expected in cases.items():
        assert order_from_store({**raw, "status": store_status}, VAT).status == expected, store_status


def test_payment_type_aliases_and_empty():
    raw = _export()["items"][0]
    assert order_from_store({**raw, "payment_type": "card"}, VAT).payment_type == PaymentType.ONLINE_CARD
    assert order_from_store({**raw, "payment_type": "online_card"}, VAT).payment_type == PaymentType.ONLINE_CARD
    assert order_from_store({**raw, "payment_type": "cod"}, VAT).payment_type == PaymentType.CASH_ON_DELIVERY
    assert order_from_store({**raw, "payment_type": "payment_order"}, VAT).payment_type == PaymentType.PAYMENT_ORDER
    assert order_from_store({**raw, "payment_type": ""}, VAT).payment_type is None


def test_orders_page_from_store_maps_pagination():
    page = orders_page_from_store(_export(), VAT)
    assert [o.order_id for o in page.items] == ["ORD-000123"]
    assert page.cursor is None
    assert page.has_more is False

    more = orders_page_from_store({**_export(), "cursor": "ORD-000123", "has_more": True}, VAT)
    assert more.cursor == "ORD-000123"
    assert more.has_more is True
```

- [ ] **Step 2: Run them, confirm they fail**

```
uv run --extra dev pytest tests/shop/bapp_store/test_orders_unit.py -v
```

Expected: collection error `ImportError: cannot import name 'order_from_store' from 'bapp_connectors.providers.shop.bapp_store.mappers'`.

- [ ] **Step 3: Extend the imports** of `src/bapp_connectors/providers/shop/bapp_store/mappers.py`. Insert `from datetime import UTC, datetime` directly above the existing `from decimal import Decimal` line, then merge the new DTO names into the existing `from bapp_connectors.core.dto import (...)` block so those two statements read as below. Every other import in the module stays untouched: `import hashlib`, `import json`, `from decimal import Decimal`, `from html.parser import HTMLParser`, `from bapp_connectors.core.pricing import to_gross, to_net` and `from bapp_connectors.providers.shop.bapp_store.models import SyncItemResult, SyncTaskResponse`.

```python
from datetime import UTC, datetime

from bapp_connectors.core.dto import (
    Address,
    BulkItemResult,
    BulkUpsertResult,
    Contact,
    Order,
    OrderItem,
    OrderStatus,
    PaginatedResult,
    PaymentStatus,
    PaymentType,
    Product,
    ProductCategory,
    ProductPhoto,
    ProductUpdate,
    ProviderMeta,
    ShopRules,
)
```

- [ ] **Step 4: Append the order mappers** at the end of the same file:

```python
# -- Order mappers --

STORE_ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    **{s.value: s for s in OrderStatus},
    "confirmed": OrderStatus.ACCEPTED,
    "completed": OrderStatus.DELIVERED,
    "canceled": OrderStatus.CANCELLED,
}

STORE_PAYMENT_STATUS_MAP: dict[str, PaymentStatus] = {s.value: s for s in PaymentStatus}

STORE_PAYMENT_TYPE_MAP: dict[str, PaymentType] = {
    **{t.value: t for t in PaymentType},
    "card": PaymentType.ONLINE_CARD,
    "cod": PaymentType.CASH_ON_DELIVERY,
    "transfer": PaymentType.BANK_TRANSFER,
}

_ORDER_TOP_LEVEL_KEYS = frozenset(
    {
        "number",
        "created_at",
        "updated_at",
        "status",
        "payment_status",
        "payment_type",
        "currency",
        "billing",
        "delivery_address",
        "items",
        "total",
        "extra",
    }
)

_LINE_KEYS = frozenset({"product_id", "sku", "name", "quantity", "unit_price", "currency", "extra"})


def _billing_from_store(data: dict | None) -> Contact | None:
    if not data:
        return None
    address = Address(
        street=data.get("address", ""),
        city=data.get("city", ""),
        region=data.get("county", ""),
        postal_code=data.get("postal_code", ""),
        country="RO",
    )
    return Contact(
        name=data.get("name", ""),
        company_name=data.get("company_name", ""),
        vat_id=data.get("vat_id", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        address=address,
        extra={"reg_com": data.get("reg_com", "")},
    )


def _line_from_store(line: dict, currency: str, vat_rate: Decimal) -> OrderItem:
    gross = str(line["unit_price"])
    extra = {k: v for k, v in line.items() if k not in _LINE_KEYS}
    extra.update(line.get("extra") or {})
    extra["gross_unit_price"] = gross
    return OrderItem(
        product_id=str(line.get("product_id", "")),
        sku=line.get("sku", ""),
        name=line.get("name", ""),
        quantity=Decimal(str(line.get("quantity", "1"))),
        unit_price=to_net(Decimal(gross), vat_rate),
        currency=line.get("currency") or currency,
        tax_rate=vat_rate,
        extra=extra,
    )


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def order_from_store(data: dict, vat_rate: Decimal) -> Order:
    number = str(data["number"])
    currency = data.get("currency", "RON")
    raw_status = data.get("status", "")
    raw_payment_status = data.get("payment_status", "")
    raw_payment_type = data.get("payment_type", "")
    gross_total = str(data.get("total", "0"))

    extra = {k: v for k, v in data.items() if k not in _ORDER_TOP_LEVEL_KEYS}
    extra.update(data.get("extra") or {})
    extra["gross_total"] = gross_total
    extra["raw_payment_status"] = raw_payment_status
    extra["raw_payment_type"] = raw_payment_type

    return Order(
        order_id=number,
        external_id=number,
        status=STORE_ORDER_STATUS_MAP.get(raw_status, OrderStatus.PENDING),
        raw_status=raw_status,
        payment_status=STORE_PAYMENT_STATUS_MAP.get(raw_payment_status, PaymentStatus.UNPAID),
        payment_type=STORE_PAYMENT_TYPE_MAP.get(raw_payment_type, PaymentType.OTHER) if raw_payment_type else None,
        currency=currency,
        items=[_line_from_store(line, currency, vat_rate) for line in data.get("items", [])],
        billing=_billing_from_store(data.get("billing")),
        delivery_address=data.get("delivery_address", ""),
        total=to_net(Decimal(gross_total), vat_rate),
        created_at=_parse_iso(data.get("created_at")),
        updated_at=_parse_iso(data.get("updated_at")),
        external_url=(data.get("extra") or {}).get("order_url", ""),
        provider_meta=ProviderMeta(provider="bapp_store", raw_id=number, raw_payload=data, fetched_at=datetime.now(UTC)),
        extra=extra,
    )


def orders_page_from_store(data: dict, vat_rate: Decimal) -> PaginatedResult[Order]:
    return PaginatedResult(
        items=[order_from_store(row, vat_rate) for row in data.get("items", [])],
        cursor=data.get("cursor"),
        has_more=bool(data.get("has_more", False)),
    )
```

- [ ] **Step 5: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_orders_unit.py -v
```

Expected: `9 passed`.

- [ ] **Step 6: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/mappers.py tests/shop/bapp_store/test_orders_unit.py
git commit -m "feat(bapp_store): map store orders to net DTOs"
```

---

### Task 13: Adapter class, product paths, bulk upsert, unsupported methods

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/adapter.py`
- Create: `tests/shop/bapp_store/test_adapter_unit.py`

**Interfaces**
- Consumes: `manifest` (Task 6); `BappStoreClient` (Task 9); `SyncTaskResponse` (Task 8); every mapper from Tasks 10, 11 and 12; `ShopPort` (`src/bapp_connectors/core/ports/shop.py:19`, abstract `get_orders`, `get_order`, `get_products`, `update_product_stock`, `update_product_price`, `update_order_status` at lines 30-55); `ProductCreationCapability` (abstract `create_product`, `delete_product`, `src/bapp_connectors/core/capabilities/product_management.py:23-34`); `ProductFullUpdateCapability` (`:37`); `ProductLookupCapability.find_product_by_sku` (`src/bapp_connectors/core/capabilities/product_lookup.py:16`); `BulkUpsertCapability` (`src/bapp_connectors/core/capabilities/bulk_operations.py:32`); `WebhookCapability` (`src/bapp_connectors/core/capabilities/webhooks.py:14`); `VolumePricingCapability` (Task 3); `CategoryManagementCapability` (`product_management.py:46`); `ConnectorError`, `PermanentProviderError`, `UnsupportedFeatureError` (`src/bapp_connectors/core/errors.py:11,64,75`); `manifest.auth.validate_credentials` (used the same way at `src/bapp_connectors/providers/shop/woocommerce/adapter.py:190`).
- Produces: `BappStoreShopAdapter(credentials: dict, http_client=None, config: dict | None = None, **kwargs)` with class attributes `manifest`, `max_batch_size = 100`, `sideloads_images = False`, `supports_modified_since = False`, `accepts_local_category_id = True`, instance attributes `credentials`, `store_url`, `token`, `_vat_rate`, `client`, and methods `validate_credentials`, `test_connection`, `get_products(cursor=None, since=None)`, `find_product_by_sku(sku)`, `bulk_upsert_products(creates, updates)`, `create_product(product)`, `update_product(update)`, `get_categories()`, `create_category(name, parent_id=None, local_id=None)`, `update_category(category)`, `push_shop_rules(rules)`, `get_orders(since=None, cursor=None)`, `get_order(order_id)`, `verify_webhook(headers, body, secret="")`, `parse_webhook(headers, body)`, plus `delete_product`, `update_product_stock`, `update_product_price`, `update_order_status` raising `UnsupportedFeatureError`.

Four of those land here as `raise NotImplementedError` stubs and are implemented in Task 14: `get_categories`, `push_shop_rules`, `verify_webhook`, `parse_webhook`. `create_category`, `update_category` and the module constant `SIGNATURE_HEADER = "X-BappStore-Signature"` are not written here at all; Task 14 adds them.

The class is an ABC over seven bases, so it cannot be instantiated while any abstract method is missing. That forces stubs for the four abstract methods this task does not exercise (`get_categories`, `push_shop_rules`, `verify_webhook`, `parse_webhook`), but nothing more: `create_category` and `update_category` are concrete on `CategoryManagementCapability` (`src/bapp_connectors/core/capabilities/product_management.py:54` and `:58`, both raising `NotImplementedError`), so they are simply absent until Task 14 writes them test-first.

- [ ] **Step 1: Write the failing tests** at `tests/shop/bapp_store/test_adapter_unit.py`:

```python
"""bapp_store adapter tests against FakeHttpClient; no store needed."""
from __future__ import annotations

import json
from decimal import Decimal
from importlib.resources import files

import pytest

from bapp_connectors.core.dto import Product, ProductUpdate
from bapp_connectors.core.errors import PermanentProviderError, UnsupportedFeatureError
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from tests.fake_http import FakeHttpClient
from tests.shop.bapp_store.fake_response import FakeResponse

FIXTURES = files("bapp_connectors.providers.shop.bapp_store") / "fixtures"
TASK_PATH = "tasks/store.CatalogSyncTask"


@pytest.fixture(scope="module")
def batch() -> dict:
    return json.loads((FIXTURES / "products_batch.json").read_text())


@pytest.fixture
def fake():
    return FakeHttpClient()


@pytest.fixture
def adapter(fake):
    return BappStoreShopAdapter(
        credentials={"store_url": "https://demo-st.sites.bapp.ro/", "token": "tok"},
        http_client=fake,
        config={"vat_rate": "0.21"},
    )


def _products(batch) -> list[Product]:
    out = []
    for record in batch["request"]["products"]:
        out.append(Product(
            product_id=record["id"], sku=record["code"], name=record["name"], price=Decimal("1.00"),
            stock=int(record["stock"]), category_ids=record["category_ids"],
            extra={"bapp": record["extra"]["bapp"], "price_tiers": []},
        ))
    return out


def test_class_attributes():
    assert BappStoreShopAdapter.sideloads_images is False
    assert BappStoreShopAdapter.supports_modified_since is False
    assert BappStoreShopAdapter.accepts_local_category_id is True
    assert BappStoreShopAdapter.max_batch_size == 100


def test_validate_credentials(adapter):
    assert adapter.validate_credentials() is True
    assert BappStoreShopAdapter(credentials={"store_url": "https://x"}).validate_credentials() is False


def test_test_connection_success(adapter, fake):
    fake.add("GET", "content-type/store.storecategory/", {"count": 0, "results": []})
    result = adapter.test_connection()
    assert result.success is True


def test_bulk_upsert_sends_one_task_and_splits_positional_results(adapter, fake, batch):
    products = _products(batch)
    response = {"categories": [], "products": [
        {"index": 0, "id": "345100", "status": "created", "error": "", "code": ""},
        {"index": 1, "id": "345101", "status": "error", "error": "category 159 unknown", "code": "unknown_category"},
        {"index": 2, "id": "345102", "status": "updated", "error": "", "code": ""},
    ], "rules_applied": False, "webhook_applied": False}
    fake.add("POST", TASK_PATH, FakeResponse(200, response))
    update = ProductUpdate(product_id="345102", stock=5, extra={"bapp": {"gross_price": "60.50"}})
    result = adapter.bulk_upsert_products(products[:2], [update])
    assert len(fake.calls) == 1
    call = fake.last_call()
    assert call.method == "POST" and call.path.endswith(TASK_PATH)
    assert call.kwargs["headers"]["X-App-Slug"] == "sync"
    sent = call.kwargs["json"]["products"]
    assert [r["id"] for r in sent] == ["345100", "345101", "345102"]
    assert sent[2] == {"id": "345102", "stock": "5", "price": {"amount": "60.50", "currency": "RON"}, "extra": {"bapp": {"gross_price": "60.50"}}}
    assert result.created[0].remote_id == "345100" and result.created[0].ok
    assert result.created[1].error_code == "unknown_category"
    assert result.updated[0].index == 0 and result.updated[0].remote_id == "345102"


def test_bulk_upsert_empty_makes_no_call(adapter, fake):
    assert adapter.bulk_upsert_products([], []).created == []
    assert fake.calls == []


def test_bulk_upsert_over_limit_raises(adapter, fake, batch):
    products = _products(batch) * 34  # 102 > 100
    with pytest.raises(ValueError):
        adapter.bulk_upsert_products(products, [])
    assert fake.calls == []


def test_create_product_returns_product_and_raises_on_item_error(adapter, fake, batch):
    product = _products(batch)[0]
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "345100", "status": "created", "error": "", "code": ""}]}))
    assert adapter.create_product(product).product_id == "345100"
    fake.responses.clear()
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "345100", "status": "error", "error": "bad price", "code": "invalid_price"}]}))
    with pytest.raises(PermanentProviderError, match="bad price"):
        adapter.create_product(product)


def test_update_product_posts_single_update_record(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"products": [{"index": 0, "id": "1", "status": "updated", "error": "", "code": ""}]}))
    adapter.update_product(ProductUpdate(product_id="1", name="Nou"))
    assert fake.last_call().kwargs["json"] == {"products": [{"id": "1", "name": "Nou"}]}


def test_find_product_by_sku_matches_exact_code(adapter, fake):
    fake.add("GET", "content-type/store.storeproduct/", {"count": 2, "next": None, "results": [
        {"id": 3, "external_id": "9", "code": "AB-10", "code_ean": "", "name": "Other", "price_amount": "12.1000", "stock_qty": "1"},
        {"id": 4, "external_id": "10", "code": "AB-1", "code_ean": "", "name": "Ciocan", "price_amount": "12.1000", "stock_qty": "1"},
    ]})
    product = adapter.find_product_by_sku("AB-1")
    assert product is not None and product.product_id == "10" and product.price == Decimal("10.00")
    assert fake.last_call().kwargs["params"]["code"] == "AB-1"


def test_find_product_by_sku_blank_short_circuits(adapter, fake):
    assert adapter.find_product_by_sku("") is None
    assert fake.calls == []


def test_get_products_pages_by_cursor(adapter, fake):
    fake.add("GET", "content-type/store.storeproduct/", {"count": 120, "next": "https://x/?page=3&page_size=100", "results": [
        {"id": 4, "external_id": "10", "code": "AB-1", "code_ean": "", "name": "Ciocan", "price_amount": "12.1000", "stock_qty": "1"},
    ]})
    page = adapter.get_products(cursor="2")
    assert fake.last_call().kwargs["params"] == {"page_size": 100, "page": 2}
    assert page.items[0].product_id == "10" and page.has_more is True and page.cursor == "3" and page.total == 120


@pytest.mark.parametrize("call", [
    lambda a: a.update_product_stock("1", 3),
    lambda a: a.update_product_price("1", Decimal("1"), "RON"),
    lambda a: a.update_order_status("1", None),
    lambda a: a.delete_product("1"),
])
def test_unsupported_methods_raise(adapter, call):
    with pytest.raises(UnsupportedFeatureError):
        call(adapter)
```

- [ ] **Step 2: Run them, confirm they fail**

```
uv run --extra dev pytest tests/shop/bapp_store/test_adapter_unit.py -v
```

Expected: collection error `ModuleNotFoundError: No module named 'bapp_connectors.providers.shop.bapp_store.adapter'`.

- [ ] **Step 3: Write the adapter** at `src/bapp_connectors/providers/shop/bapp_store/adapter.py`:

```python
"""
Company Store (BAPP) shop adapter: pushes the BAPP catalogue into a tenant store through
CatalogSyncTask and reads orders back through the export tasks.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from bapp_connectors.core.capabilities import (
    BulkUpsertCapability,
    CategoryManagementCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    WebhookCapability,
)
from bapp_connectors.core.capabilities.volume_pricing import VolumePricingCapability
from bapp_connectors.core.dto import (
    BulkUpsertResult,
    ConnectionTestResult,
    Order,
    OrderStatus,
    PaginatedResult,
    Product,
    ProductCategory,
    ProductUpdate,
    ShopRules,
    WebhookEvent,
)
from bapp_connectors.core.errors import ConnectorError, PermanentProviderError, UnsupportedFeatureError
from bapp_connectors.core.ports import ShopPort
from bapp_connectors.providers.shop.bapp_store.client import BappStoreClient
from bapp_connectors.providers.shop.bapp_store.manifest import manifest
from bapp_connectors.providers.shop.bapp_store.mappers import (
    bulk_result_from_response,
    order_from_store,
    orders_page_from_store,
    product_from_store,
    product_to_record,
    update_to_record,
)

if TYPE_CHECKING:
    from datetime import datetime


class BappStoreShopAdapter(
    ShopPort,
    BulkUpsertCapability,
    ProductCreationCapability,
    ProductFullUpdateCapability,
    ProductLookupCapability,
    CategoryManagementCapability,
    VolumePricingCapability,
    WebhookCapability,
):
    manifest = manifest
    max_batch_size = 100
    sideloads_images = False
    supports_modified_since = False
    accepts_local_category_id = True

    def __init__(self, credentials: dict, http_client=None, config: dict | None = None, **kwargs):
        self.credentials = credentials
        config = config or {}
        self.store_url = credentials.get("store_url", "")
        self.token = credentials.get("token", "")
        self._vat_rate = Decimal(str(config.get("vat_rate", "0.21")))
        self.client = BappStoreClient(self.store_url, self.token, http_client=http_client)

    # -- BasePort --

    def validate_credentials(self) -> bool:
        return not self.manifest.auth.validate_credentials(self.credentials)

    def test_connection(self) -> ConnectionTestResult:
        try:
            ok = self.client.test_auth()
        except ConnectorError as e:
            return ConnectionTestResult(success=False, message=str(e))
        return ConnectionTestResult(success=ok, message="Connection successful" if ok else "Authentication failed")

    # -- Products --

    def get_products(self, cursor: str | None = None, since: datetime | None = None) -> PaginatedResult[Product]:
        page = int(cursor) if cursor else 1
        data = self.client.find_products(page=page)
        has_more = bool(data.get("next"))
        return PaginatedResult(
            items=[product_from_store(row, self._vat_rate) for row in data.get("results", [])],
            cursor=str(page + 1) if has_more else None,
            has_more=has_more,
            total=data.get("count"),
        )

    def find_product_by_sku(self, sku: str) -> Product | None:
        if not sku:
            return None
        data = self.client.find_products(code=sku)
        # `code` is a declared filterset field on the store viewset, but the loop stays: only an exact match is an adoption candidate.
        for row in data.get("results", []):
            if row.get("code") == sku:
                return product_from_store(row, self._vat_rate)
        return None

    def bulk_upsert_products(self, creates: list[Product], updates: list[ProductUpdate]) -> BulkUpsertResult:
        total = len(creates) + len(updates)
        if total == 0:
            return BulkUpsertResult()
        if total > self.max_batch_size:
            raise ValueError(f"CatalogSyncTask accepts at most {self.max_batch_size} products, got {total}")
        records = [product_to_record(p, self._vat_rate) for p in creates] + [update_to_record(u, self._vat_rate) for u in updates]
        response = self.client.sync_task({"products": records})
        return bulk_result_from_response(
            response, len(creates), len(updates), [p.product_id for p in creates], [u.product_id for u in updates],
        )

    def create_product(self, product: Product) -> Product:
        result = self.bulk_upsert_products([product], [])
        self._raise_single(result.created, product.product_id)
        return product

    def update_product(self, update: ProductUpdate) -> None:
        result = self.bulk_upsert_products([], [update])
        self._raise_single(result.updated, update.product_id)

    @staticmethod
    def _raise_single(items, product_id: str) -> None:
        if not items:
            raise PermanentProviderError(f"no result returned for product {product_id}")
        if items[0].error:
            raise PermanentProviderError(items[0].error, code=items[0].error_code)

    def delete_product(self, product_id: str) -> None:
        raise UnsupportedFeatureError("bapp_store never prunes products; deactivate them instead")

    def update_product_stock(self, product_id: str, quantity: int) -> None:
        raise UnsupportedFeatureError("bapp_store updates stock through bulk_upsert_products")

    def update_product_price(self, product_id: str, price: Decimal, currency: str) -> None:
        raise UnsupportedFeatureError("bapp_store updates prices through bulk_upsert_products")

    # -- Categories and volume pricing --

    def get_categories(self) -> list[ProductCategory]:
        raise NotImplementedError

    def push_shop_rules(self, rules: ShopRules) -> None:
        raise NotImplementedError

    # -- Orders --

    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        data = self.client.export_orders(since=since.isoformat() if since else None, cursor=cursor)
        return orders_page_from_store(data, self._vat_rate)

    def get_order(self, order_id: str) -> Order:
        return order_from_store(self.client.export_order(order_id), self._vat_rate)

    def update_order_status(self, order_id: str, status: OrderStatus) -> Order:
        raise UnsupportedFeatureError("bapp_store does not accept order status updates")

    # -- Webhooks --

    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        raise NotImplementedError

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        raise NotImplementedError
```

- [ ] **Step 4: Run the tests, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store/test_adapter_unit.py -v
```

Expected: `15 passed` (11 plain tests plus `test_unsupported_methods_raise`, parametrised 4 ways).

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/adapter.py tests/shop/bapp_store/test_adapter_unit.py
git commit -m "feat(bapp_store): shop adapter with bulk upsert, lookup and product paging"
```

---

### Task 14: Category, rules and webhook adapter methods

**Files**
- Modify: `tests/shop/bapp_store/test_adapter_unit.py` (imports and append)
- Modify: `src/bapp_connectors/providers/shop/bapp_store/adapter.py` (replace the four `NotImplementedError` stubs, add `create_category`, `update_category`, `_raise_category`, `SIGNATURE_HEADER`, `_WEBHOOK_EVENTS` and the mapper and model imports they need)

**Interfaces**
- Consumes: `BappStoreShopAdapter` and its `self.client` / `self._vat_rate` (Task 13); `category_from_store`, `category_record`, `rules_to_body` (Tasks 10 and 11); `SyncTaskResponse` (Task 8); `fixtures/rules.json` and `fixtures/products_batch.json` (Task 1); `ShopRules`, `OrderValueTier`, `ProductCategory`, `WebhookEventType` (`bapp_connectors.core.dto`).
- Produces: working `get_categories()`, `create_category(name, parent_id=None, local_id=None)`, `update_category(category)`, `push_shop_rules(rules)`, `verify_webhook(headers, body, secret="")`, `parse_webhook(headers, body)`, the private helper `_raise_category`, and the module constant `SIGNATURE_HEADER = "X-BappStore-Signature"`.

- [ ] **Step 1: Append the tests** to `tests/shop/bapp_store/test_adapter_unit.py`. First extend the file's imports: put `import hashlib` and `import hmac` above the existing `import json`, and widen the DTO import to

```python
from bapp_connectors.core.dto import OrderValueTier, Product, ProductCategory, ProductUpdate, ShopRules, WebhookEventType
```

Then append:

```python


@pytest.fixture(scope="module")
def rules_fixture() -> dict:
    return json.loads((FIXTURES / "rules.json").read_text())


def test_get_categories_remaps_bare_parent_pk_to_external_id(adapter, fake):
    fake.add("GET", "content-type/store.storecategory/", {"count": 2, "next": None, "results": [
        {"id": 5, "external_id": "159", "name": "Scule", "parent": None, "is_active": True},
        {"id": 7, "external_id": "160", "name": "Burghie", "parent": 5, "is_active": True},
    ]})
    categories = adapter.get_categories()
    assert [(c.category_id, c.parent_id) for c in categories] == [("159", None), ("160", "159")]


def test_create_category_sends_local_id_record(adapter, fake, batch):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "created", "error": "", "code": ""}]}))
    created = adapter.create_category("Burghie", parent_id="159", local_id="160")
    assert fake.last_call().kwargs["json"] == {"categories": [batch["request"]["categories"][1]]}
    assert created.category_id == "160" and created.parent_id == "159" and created.name == "Burghie"


def test_create_category_without_local_id_is_rejected(adapter, fake):
    with pytest.raises(ValueError):
        adapter.create_category("Scule")
    assert fake.calls == []


def test_create_category_item_error_raises(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "error", "error": "parent 999 unknown", "code": "unknown_category"}]}))
    with pytest.raises(PermanentProviderError, match="parent 999 unknown"):
        adapter.create_category("Burghie", parent_id="999", local_id="160")


def test_update_category_sends_name_and_parent(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"categories": [{"index": 0, "id": "160", "status": "updated", "error": "", "code": ""}]}))
    result = adapter.update_category(ProductCategory(category_id="160", name="Burghie HSS", parent_id="159"))
    assert fake.last_call().kwargs["json"] == {"categories": [{"id": "160", "parent_id": "159", "name": "Burghie HSS"}]}
    assert result.category_id == "160"


def test_push_shop_rules_body_matches_fixture(adapter, fake, rules_fixture):
    fake.add("POST", TASK_PATH, FakeResponse(200, rules_fixture["response"]))
    rules = ShopRules(
        order_value_tiers=[
            OrderValueTier(min_total=Decimal("5000.00"), discount_percent=Decimal("3.00")),
            OrderValueTier(min_total=Decimal("10000.00"), discount_percent=Decimal("5.00")),
        ],
        min_order_total=Decimal("1000.00"),
        currency="RON",
        extra={"connection_id": 123, "synced_at": "2026-09-02T12:00:00+03:00"},
    )
    adapter.push_shop_rules(rules)
    assert fake.last_call().kwargs["json"] == rules_fixture["request"]


def test_push_shop_rules_not_applied_raises(adapter, fake):
    fake.add("POST", TASK_PATH, FakeResponse(200, {"rules_applied": False}))
    with pytest.raises(PermanentProviderError):
        adapter.push_shop_rules(ShopRules(currency="RON"))


def test_verify_webhook_hex_hmac_over_body(adapter):
    body = json.dumps({"id": "ORD-000123", "event": "order.created"}).encode()
    good = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="s3cret") is True
    assert adapter.verify_webhook({"x-bappstore-signature": good.upper()}, body, secret="s3cret") is True
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body + b" ", secret="s3cret") is False
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="other") is False
    assert adapter.verify_webhook({}, body, secret="s3cret") is False
    assert adapter.verify_webhook({"X-BappStore-Signature": good}, body, secret="") is False


def test_parse_webhook_maps_event_and_order_id(adapter):
    body = json.dumps({"id": "ORD-000123", "event": "order.created"}).encode()
    event = adapter.parse_webhook({}, body)
    assert event.event_type is WebhookEventType.ORDER_CREATED
    assert event.provider == "bapp_store" and event.provider_event_type == "order.created"
    assert event.payload == {"id": "ORD-000123"}
    assert event.idempotency_key == "order.created:ORD-000123"


def test_parse_webhook_unknown_event(adapter):
    event = adapter.parse_webhook({}, json.dumps({"id": "1", "event": "order.deleted"}).encode())
    assert event.event_type is WebhookEventType.UNKNOWN
```

- [ ] **Step 2: Run them, confirm they fail**

```
uv run --extra dev pytest tests/shop/bapp_store/test_adapter_unit.py -v -k "categor or rules or webhook"
```

Expected: `10 failed`, and no Task 13 test is selected (none of their names contains `categor`, `rules` or `webhook`). The four stubbed methods account for six of them, each failing with a bare `NotImplementedError`. The two `create_category` tests that pass `local_id=` fail with `TypeError: create_category() got an unexpected keyword argument 'local_id'`, because the inherited signature is `create_category(self, name, parent_id=None)`. `test_create_category_without_local_id_is_rejected` expects `ValueError` and instead sees the base class message `NotImplementedError: This provider does not support category creation.` (`src/bapp_connectors/core/capabilities/product_management.py:56`), and `test_update_category_sends_name_and_parent` sees `NotImplementedError: This provider does not support category updates.` (`:60`).

- [ ] **Step 3: Write the methods.** In `src/bapp_connectors/providers/shop/bapp_store/adapter.py`, add `import hashlib`, `import hmac` and `import json` above `from decimal import Decimal`; add `WebhookEventType` to the `from bapp_connectors.core.dto import (...)` block; add `category_from_store`, `category_record` and `rules_to_body` to the `from ...mappers import (...)` block; add `from bapp_connectors.providers.shop.bapp_store.models import SyncTaskResponse` below it; and add the two module constants directly above `class BappStoreShopAdapter`:

```python
SIGNATURE_HEADER = "X-BappStore-Signature"

_WEBHOOK_EVENTS = {
    "order.created": WebhookEventType.ORDER_CREATED,
    "order.updated": WebhookEventType.ORDER_UPDATED,
}
```

Then replace the `# -- Categories and volume pricing --` heading and its two stubs with:

```python
    # -- Categories --

    def get_categories(self) -> list[ProductCategory]:
        categories = [category_from_store(row) for row in self.client.list_categories()]
        by_store_id = {c.extra["store_id"]: c.category_id for c in categories}
        return [c.model_copy(update={"parent_id": by_store_id.get(c.parent_id, c.parent_id)}) for c in categories]

    def create_category(self, name: str, parent_id: str | None = None, local_id: str | None = None) -> ProductCategory:
        if not local_id:
            raise ValueError("bapp_store categories are keyed by the BAPP category id; local_id is required")
        response = self.client.sync_task({"categories": [category_record(name, parent_id, local_id)]})
        self._raise_category(response, local_id)
        return ProductCategory(category_id=local_id, name=name, parent_id=parent_id)

    def update_category(self, category: ProductCategory) -> ProductCategory:
        # Name and parent only (spec 2.2): a store-side activation toggle is not BAPP's to overwrite on a rename.
        response = self.client.sync_task({"categories": [category_record(category.name, category.parent_id, category.category_id, is_active=None)]})
        self._raise_category(response, category.category_id)
        return category

    @staticmethod
    def _raise_category(response: dict, local_id: str) -> None:
        items = SyncTaskResponse.model_validate(response).categories
        if not items:
            raise PermanentProviderError(f"no result returned for category {local_id}")
        if items[0].error:
            raise PermanentProviderError(items[0].error, code=items[0].code)

    # -- Volume pricing --

    def push_shop_rules(self, rules: ShopRules) -> None:
        response = self.client.sync_task({"rules": rules_to_body(rules)})
        if not SyncTaskResponse.model_validate(response).rules_applied:
            raise PermanentProviderError("store did not apply the pricing rules")
```

and replace the two stubs under `# -- Webhooks --` with:

```python
    def verify_webhook(self, headers: dict, body: bytes, secret: str = "") -> bool:
        signature = next((v for k, v in headers.items() if k.lower() == SIGNATURE_HEADER.lower()), "")
        if not signature or not secret:
            return False
        computed = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.lower(), computed)

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        data = json.loads(body)
        event = str(data.get("event", ""))
        order_id = str(data.get("id", ""))
        key = f"{event}:{order_id}"
        return WebhookEvent(
            event_id=key,
            event_type=_WEBHOOK_EVENTS.get(event, WebhookEventType.UNKNOWN),
            provider="bapp_store",
            provider_event_type=event,
            payload={"id": order_id},
            idempotency_key=key,
        )
```

- [ ] **Step 4: Run the whole provider suite**

```
uv run --extra dev pytest tests/shop/bapp_store -v
```

Expected: all green: 20 mapper tests, 25 adapter tests, 13 client tests, 10 error tests, 6 manifest tests, 9 order tests, 1 fixtures test. If `test_get_categories_remaps_bare_parent_pk_to_external_id` fails with a pydantic frozen-instance error, the `model_copy` call in `get_categories` is the place to look: `model_copy(update=...)` is the supported way to derive a new frozen instance.

- [ ] **Step 5: Commit**

```bash
git add tests/shop/bapp_store/test_adapter_unit.py src/bapp_connectors/providers/shop/bapp_store/adapter.py
git commit -m "feat(bapp_store): category, rules and webhook adapter methods"
```

---

### Task 15: Adapter order paths treat a naive since as UTC

**Files**
- Modify: `src/bapp_connectors/providers/shop/bapp_store/adapter.py` (method `get_orders`)
- Modify: `tests/shop/bapp_store/test_orders_unit.py` (imports and append)

**Interfaces**
- Consumes: `BappStoreClient.export_orders(since: str | None, cursor: str | None, limit: int = 50) -> dict` and `BappStoreClient.export_order(number: str) -> dict` (Task 9); `BappStoreShopAdapter.__init__` setting `self.client` and `self._vat_rate` (Task 13); `order_from_store`, `orders_page_from_store` (Task 12).
- Produces: `get_orders` sends `since` as an ISO-8601 string with an offset, treating a naive datetime as UTC so the store's `updated_at` filter compares timezone-aware values. The cursor stays opaque to the adapter: the store returns the last order number (spec 4.7).

- [ ] **Step 1: Append the failing tests.** First replace the whole header of `tests/shop/bapp_store/test_orders_unit.py`, down to and including the last import, with this complete block. `json`, `Decimal` and `Path` are still used by `_export()` and the mapper tests written in Task 12; only the `datetime` line and the adapter import change:

```python
"""Order mapper tests for the bapp_store provider. Pure functions, no network."""
import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from bapp_connectors.core.dto import OrderStatus, PaymentStatus, PaymentType
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from bapp_connectors.providers.shop.bapp_store.mappers import order_from_store, orders_page_from_store
```

Then append at the end of the file:

```python
class _FakeClient:
    def __init__(self, export: dict):
        self.export = export
        self.calls: list[tuple] = []

    def export_orders(self, since=None, cursor=None, limit=50):
        self.calls.append(("export_orders", since, cursor, limit))
        return self.export

    def export_order(self, number):
        self.calls.append(("export_order", number))
        return self.export["items"][0]


def _adapter(export: dict) -> tuple[BappStoreShopAdapter, _FakeClient]:
    adapter = BappStoreShopAdapter({"store_url": "https://demo.sites.bapp.ro", "token": "t"}, config={"vat_rate": "0.21"})
    fake = _FakeClient(export)
    adapter.client = fake
    return adapter, fake


def test_get_orders_passes_since_and_cursor_and_maps_page():
    adapter, fake = _adapter(_export())
    page = adapter.get_orders(since=datetime(2026, 9, 1, 12, 0, tzinfo=UTC), cursor="ORD-000100")
    assert fake.calls == [("export_orders", "2026-09-01T12:00:00+00:00", "ORD-000100", 50)]
    assert [o.order_id for o in page.items] == ["ORD-000123"]
    assert page.items[0].items[0].unit_price == Decimal("95.00")
    assert page.has_more is False


def test_get_orders_without_filters_sends_none():
    adapter, fake = _adapter(_export())
    adapter.get_orders()
    assert fake.calls == [("export_orders", None, None, 50)]


def test_get_orders_treats_naive_since_as_utc():
    adapter, fake = _adapter(_export())
    adapter.get_orders(since=datetime(2026, 9, 1, 12, 0))
    assert fake.calls[0][1] == "2026-09-01T12:00:00+00:00"


def test_get_order_maps_single_export():
    adapter, fake = _adapter(_export())
    order = adapter.get_order("ORD-000123")
    assert fake.calls == [("export_order", "ORD-000123")]
    assert order.order_id == "ORD-000123"
    assert order.total == Decimal("8140.56")
```

- [ ] **Step 2: Run them, confirm one fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_orders_unit.py -v -k "get_order"
```

Expected: `test_get_orders_treats_naive_since_as_utc` fails with `AssertionError: assert '2026-09-01T12:00:00' == '2026-09-01T12:00:00+00:00'`; the other three pass.

- [ ] **Step 3: Normalise the timestamp.** In `src/bapp_connectors/providers/shop/bapp_store/adapter.py`, add `UTC` to the datetime import so the top of the file reads:

```python
from datetime import UTC

if TYPE_CHECKING:
    from datetime import datetime
```

and replace the body of `get_orders` with:

```python
    def get_orders(self, since: datetime | None = None, cursor: str | None = None) -> PaginatedResult[Order]:
        since_iso = None
        if since is not None:
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            since_iso = since.isoformat()
        return orders_page_from_store(self.client.export_orders(since=since_iso, cursor=cursor), self._vat_rate)
```

- [ ] **Step 4: Run the whole provider suite, confirm it passes**

```
uv run --extra dev pytest tests/shop/bapp_store -v
```

Expected: all pass, including the 13 tests in `test_orders_unit.py`.

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/adapter.py tests/shop/bapp_store/test_orders_unit.py
git commit -m "feat(bapp_store): pull orders through the export tasks"
```

---

### Task 16: Registry registration

**Files**
- Modify: `src/bapp_connectors/providers/shop/bapp_store/__init__.py` (replace the docstring-only file)
- Modify: `tests/shop/bapp_store/test_manifest.py` (append one test)

**Interfaces**
- Consumes: `BappStoreShopAdapter` (Task 13; the class carries `manifest = manifest` and implements every capability listed in the manifest, otherwise `registry.register` raises `ConfigurationError`, `src/bapp_connectors/core/registry.py:55-60`); the module-level `registry` instance (`bapp_connectors.core.registry`, used the same way at `src/bapp_connectors/providers/shop/woocommerce/__init__.py:3`).
- Produces: `registry.get_adapter_class("shop", "bapp_store")` and `registry.get_manifest("shop", "bapp_store")` resolve once the package is imported. `scripts/update_readme.py:39-40` then discovers the provider.

- [ ] **Step 1: Append the failing test** to `tests/shop/bapp_store/test_manifest.py`:

```python
def test_package_import_registers_the_adapter():
    import bapp_connectors.providers.shop.bapp_store  # noqa: F401
    from bapp_connectors.core.registry import registry
    from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter

    assert registry.get_adapter_class("shop", "bapp_store") is BappStoreShopAdapter
    assert registry.get_manifest("shop", "bapp_store") is manifest
```

- [ ] **Step 2: Run it, confirm it fails**

```
uv run --extra dev pytest tests/shop/bapp_store/test_manifest.py -v -k registers
```

Expected: `bapp_connectors.core.errors.ConfigurationError: No adapter registered for 'shop.bapp_store'.`

- [ ] **Step 3: Register on import.** Replace `src/bapp_connectors/providers/shop/bapp_store/__init__.py` with:

```python
"""Company Store (BAPP) shop provider."""

from bapp_connectors.core.registry import registry
from bapp_connectors.providers.shop.bapp_store.adapter import BappStoreShopAdapter
from bapp_connectors.providers.shop.bapp_store.manifest import manifest

__all__ = ["BappStoreShopAdapter", "manifest"]

registry.register(BappStoreShopAdapter)
```

- [ ] **Step 4: Run the whole provider suite, confirm it passes**

```
uv run --extra dev pytest tests/shop/bapp_store -v
```

Expected: all pass (7 in `test_manifest.py`, 10 in `test_errors_unit.py`, 12 in `test_client_unit.py`, 20 in `test_mappers_unit.py`, 25 in `test_adapter_unit.py`, 13 in `test_orders_unit.py`, 1 in `test_fixtures_parity.py`).

- [ ] **Step 5: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/__init__.py tests/shop/bapp_store/test_manifest.py
git commit -m "feat(bapp_store): register the adapter"
```

---

### Task 17: Pricing parity against pricing_cases.json

**Files**
- Modify: `tests/shop/bapp_store/test_fixtures_parity.py` (imports and append)

**Interfaces**
- Consumes: `to_gross` (`src/bapp_connectors/core/pricing.py:22`); the `fixtures/pricing_cases.json` file from Task 1.
- Produces: nothing new. The test pins the connector's `to_gross` rounding to the store's `gross_list`, so both repos agree on the list price a customer sees.

Only `tax == "21"` products of cases with a non-empty `price_modifier` are exercised: the connector never applies the channel modifier itself (the BAPP side does, before the record is built), so the test reproduces that step inline. The fixture's other cases are deliberately parsed but not asserted, because the behaviour they describe lives entirely in the store: the tier ladder (including the HALF_UP edge `114.95 * 0.95 = 109.2025 -> 109.20`), the `half_up_tier_no_vat` case at `tax == "0"` and `no_rules_at_all` all exercise the store's runtime discount engine, and this package has no counterpart to compare them against -- it ships list prices and a rules envelope, never a computed tier price. The company-store repo owns those assertions.

- [ ] **Step 1: Append the test.** First replace the import block at the top of `tests/shop/bapp_store/test_fixtures_parity.py` with:

```python
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from bapp_connectors.core.pricing import to_gross
```

Then append at the end of the file:

```python
_CASES = _load("pricing_cases.json")["cases"]
_PARITY = [
    (case["name"], code, product, case["expected"]["products"][code]["gross_list"], case["price_modifier"])
    for case in _CASES
    if case["price_modifier"]
    for code, product in case["products"].items()
    if product["tax"] == "21"
]


def _apply_modifier(net: Decimal, modifier: str) -> Decimal:
    # The BAPP channel modifier is a signed percent string such as "-5%":
    # modified = net * (1 + pct / 100), kept at 4dp like the ERP price column.
    pct = Decimal(modifier.rstrip("%"))
    return (net * (1 + pct / Decimal("100"))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@pytest.mark.parametrize("case_name,code,product,expected_gross,modifier", _PARITY, ids=[f"{c}-{p}" for c, p, *_ in _PARITY])
def test_gross_list_matches_store_for_21_percent(case_name, code, product, expected_gross, modifier):
    # Store side: gross_list = round_half_up(modified_net * 1.21, 2), e.g. 100 -> 95 -> 114.95, 70 -> 66.5 -> 80.465 -> 80.47.
    modified_net = _apply_modifier(Decimal(product["net"]), modifier)
    assert to_gross(modified_net, Decimal("0.21")) == Decimal(expected_gross)


def test_parity_selection_covers_every_21_percent_product():
    assert sorted(f"{c}-{p}" for c, p, *_ in _PARITY) == [
        "below_minimum-P",
        "below_minimum-Q",
        "category_ancestor_rule-U",
        "non_discountable_no_ladder-T",
        "worked_example-P",
        "worked_example-Q",
    ]
```

- [ ] **Step 2: Run it, confirm it passes**

This is a characterization test of the existing `to_gross`; it goes green immediately, and its value is that it turns red if either repo changes rounding.

```
uv run --extra dev pytest tests/shop/bapp_store/test_fixtures_parity.py -v
```

Expected: `8 passed` (1 file test, 6 parametrized, 1 selection test). The ids include `worked_example-Q`, where `66.5 * 1.21 = 80.465` rounds HALF_UP to `80.47`, and `non_discountable_no_ladder-T`, where `47.5 * 1.21 = 57.475` rounds to `57.48`.

- [ ] **Step 3: Prove the test bites**

Temporarily change `Decimal("0.21")` to `Decimal("0.19")` inside `test_gross_list_matches_store_for_21_percent`, rerun the same command, and expect `6 failed` with messages like `assert Decimal('113.05') == Decimal('114.95')`. Revert the edit, then confirm with `git diff --stat tests/shop/bapp_store/test_fixtures_parity.py` that only the appended lines remain.

- [ ] **Step 4: Commit**

```bash
git add tests/shop/bapp_store/test_fixtures_parity.py
git commit -m "test(bapp_store): pin gross list rounding to the store parity cases"
```

---

### Task 18: Provider README

**Files**
- Create: `src/bapp_connectors/providers/shop/bapp_store/README.md`

**Interfaces**
- Consumes: nothing executable. Documents the manifest (Task 6), the client (Task 9) and the adapter method list (Tasks 13 to 15).
- Produces: the provider README. `scripts/update_readme.py:25-40` reads the registry only, so no root README markers change here.

- [ ] **Step 1: Write the file** at `src/bapp_connectors/providers/shop/bapp_store/README.md`:

```markdown
# Company Store (BAPP)

Catalog push, volume pricing rules and order pull for a BAPP Company Store tenant.

- **API:** the store's `/api/` (bapp_framework content-type reads and DirectTask endpoints)
- **Base URL:** `<store_url>/api/`
- **Auth:** `Authorization: Token <token>` plus `X-App-Slug: sync` on every call
- **Webhooks:** Supported (HMAC-SHA256 hex over the raw body in `X-BappStore-Signature`), events `order.created`, `order.updated`
- **Rate limit:** 10 req/s, burst 10

## Credentials

| Field | Label | Required | Sensitive | Role |
|-------|-------|----------|-----------|------|
| `store_url` | Store URL | Yes | No | endpoint (internal `*-st.sites.bapp.ro` host) |
| `token` | Sync Token | Yes | Yes | store API token scoped to the `sync` app |

## Settings

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `prices_include_vat` | bool | `true` | Store prices are gross. |
| `vat_rate` | str | `0.21` | Decimal VAT rate for net/gross conversion. |
| `batch_size` | int | `100` | Products per CatalogSyncTask call; the store rejects more than 100 with 413. |
| `pause_seconds` | int | `1` | Pause between batches. |
| `publish_status` | select | `publish` | `publish` or `draft` for new products. |
| `sync_images` | bool | `true` | Send photo URLs (the store keeps URLs, no sideloading). |

Only `vat_rate` is consumed by this adapter. `prices_include_vat`, `batch_size`, `pause_seconds`, `publish_status` and `sync_images` are read by the caller (the BAPP panel sync service) when it builds the Product DTOs and slices batches; the adapter sends whatever it is given, up to the hard 100-record ceiling.

## Endpoints used

| Client method | Request |
|---------------|---------|
| `test_auth` | `GET content-type/store.storecategory/?page_size=1` |
| `sync_task` | `POST tasks/store.CatalogSyncTask` with any of `categories`, `products`, `rules`, `webhook` |
| `list_categories` | `GET content-type/store.storecategory/?page_size=100`, then every `next` page |
| `find_products` | `GET content-type/store.storeproduct/?code=<sku>&page_size=100&page=<n>` |
| `export_orders` | `GET tasks/store.OrdersExportTask?since=&cursor=&limit=` |
| `export_order` | `GET tasks/store.OrderExportTask?number=` |
| `set_webhook` | `sync_task({"webhook": {"url", "secret"}})` |

A create carries `is_active`; an update carries `id`, `parent_id` and `name` only (spec 2.2), so a store-side activation toggle survives a rename. Reads of the two content-type viewsets are page-number paged: `page` and `page_size`, `page_size` capped at 100.

The sync task response is positional: `products[i]` answers `products[i]` of the request with `status` `created`, `updated` or `error` and an error `code` (`validation`, `unknown_category`, `invalid_price`, `external_id_conflict`). The codes travel opaquely: the mappers copy `code` into `BulkItemResult.error_code` and the adapter into `PermanentProviderError.code` without branching on any value, so all four behave alike. The task upserts and never prunes.

## Errors

401/403 -> `AuthenticationError`; other 4xx (400 malformed envelope, 413 over 100 products or 8 MB) -> `PermanentProviderError`; 5xx and timeouts -> retryable `ProviderError`. The adapter guards the 100-record half of the 413 rule client-side (`bulk_upsert_products` raises `ValueError`); the 8 MB envelope cap is not measured here, so a photo-heavy batch under 100 records can still come back 413 as a `PermanentProviderError`. Callers that send long photo lists should slice smaller than 100. `sync_task` is never retried by the HTTP layer because the store may have applied the batch before a timeout.

## Not supported

`update_order_status`, `update_product_stock`, `update_product_price` raise `UnsupportedFeatureError`: the engine uses full updates and bulk upsert instead, and status echo to the store is a later version.

## Fixtures

`fixtures/` holds the cross-repo contract samples (`products_batch.json`, `rules.json`, `orders_export.json`, `pricing_cases.json`) and is their canonical home. The same files live in the company-store and aio-backend test trees; change them here, copy them over, and compare copies with `json.loads` rather than with a digest.
```

- [ ] **Step 2: Commit**

```bash
git add src/bapp_connectors/providers/shop/bapp_store/README.md
git commit -m "docs(bapp_store): provider README"
```

---

### Task 19: Regenerate the root README providers table

**Files**
- Modify: `README.md` (only the generated blocks between `<!-- PROVIDERS:BEGIN -->` / `<!-- PROVIDERS:END -->` and `<!-- STRUCTURE:BEGIN -->` / `<!-- STRUCTURE:END -->`)

**Interfaces**
- Consumes: the registered manifest `bapp_store` / `Company Store (BAPP)` (Tasks 6 and 16) and `src/bapp_connectors/providers/shop/bapp_store/adapter.py` (Task 13); `scripts/update_readme.py` discovers a provider only when `adapter.py` exists (`scripts/update_readme.py:39-40`).
- Produces: README rows for the new provider. No code.

- [ ] **Step 1: Run the generator with every optional extra installed**

```bash
uv run --extra dev --extra sftp --extra s3 --extra mobilpay python scripts/update_readme.py
```

Expected: the script prints the providers it found and reports README.md updated; `bapp_store` appears under the `shop` family, and `MobilPay`, `SFTP` and `S3 Storage` are still listed.

MobilPay, SFTP and S3 register only when `pyOpenSSL`, `paramiko` and `boto3` are importable (CLAUDE.md, "Conditional registration"). Running the generator without those extras silently drops them from the table and lowers the totals. This is not hypothetical: a plain `uv run python scripts/update_readme.py` on 2026-09-03 removed MobilPay and turned the payment count from 8 into 7. The pre-commit hook runs the same script, so a commit made in an environment without the extras reintroduces the regression even after you fix the file by hand; use `git commit --no-verify` if the hook keeps stripping providers, and say so in the commit body.

- [ ] **Step 2: Verify the diff only adds**

```bash
git diff --stat README.md
git diff README.md | grep "^[+-]" | grep -v "^+++\|^---"
```

Expected: added lines contain `bapp_store` and `Company Store (BAPP)` in the providers table and `bapp_store/` (with `fixtures/`) in the structure tree; the shop count goes from 10 to 11 and the total from 60 to 61. If any provider name disappears, an extra was missing: restore the file with `git checkout -- README.md` and rerun Step 1 with the full extras list.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: list the bapp_store shop provider"
```

---

### Task 20: PROVIDER_GUIDE notes and version 0.29.0

**Files**
- Modify: `docs/PROVIDER_GUIDE.md:555-567` (capability table, one row after the `BulkImportCapability` row at line 558) and `docs/PROVIDER_GUIDE.md:700-701` (append bullets after the `update_category` bullet)
- Modify: `pyproject.toml:3` (`version`)
- Modify: `uv.lock:47` (regenerated by `uv lock`)

**Interfaces**
- Consumes: the core attributes and capability from Tasks 3, 4 and 5.
- Produces: package version `0.29.0`, which the consumer (aio-backend) pins against.

- [ ] **Step 1: Document the attributes and the capability**

In `docs/PROVIDER_GUIDE.md`, after the bullet at lines 700-701:

```markdown
- `CategoryManagementCapability.update_category(category)` lets consumers rename/re-parent
  already-mapped categories instead of duplicating them.
```

append:

```markdown
- Set `CategoryManagementCapability.accepts_local_category_id = True` when the provider can store
  the caller's category id; `ProductSyncEngine.sync_categories` then calls
  `create_category(name, parent_id, local_id=<local category_id>)` so a re-run finds the category
  by that id instead of by name. Adapters that leave it False keep the two-argument signature.
- Set `ShopPort.sideloads_images = False` when the provider stores image URLs only and fetches
  them itself; consumers may then relax image batch caps. The default (True) means the adapter
  uploads image bytes on every product create or update.
- `VolumePricingCapability.push_shop_rules(rules: ShopRules)` pushes shop-wide order-value
  discount tiers and a minimum order total. Product DTOs for such an adapter carry
  `extra["price_tiers"]` (materialised gross unit prices per quantity step) and `extra["bapp"]`
  (`gross_price`, `vat_rate`, `unit`, `discountable`).
```

In the capability table, after the row at line 558:

```markdown
| `BulkImportCapability` | `bulk_import_products(products) -> BulkResult` |
```

insert:

```markdown
| `VolumePricingCapability` | `push_shop_rules(rules: ShopRules) -> None` |
```

- [ ] **Step 2: Bump the version**

```bash
sed -i '' 's/^version = "0.28.3"$/version = "0.29.0"/' pyproject.toml
uv lock
```

- [ ] **Step 3: Verify the version**

```bash
grep -n '^version' pyproject.toml && grep -n -A1 '^name = "bapp-connectors"' uv.lock
```

Expected: `3:version = "0.29.0"` from `pyproject.toml` and the lock entry `version = "0.29.0"` under `name = "bapp-connectors"`.

- [ ] **Step 4: Run both suites, confirm they pass**

```
uv run --extra dev pytest tests/shop/bapp_store tests/core -v
```

Expected: all pass, including the 10 core tests added by Tasks 2 to 5 (4 + 2 in `test_volume_pricing.py`, 3 in `test_engine_category_local_id.py`, 1 in `test_shop_port_since.py`) and the 96 provider tests.

- [ ] **Step 5: Commit**

```bash
git add docs/PROVIDER_GUIDE.md pyproject.toml uv.lock
git commit -m "chore: v0.29.0 with volume pricing, local category ids and sideloads_images"
```
