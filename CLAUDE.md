# Claude Code Context — bapp-connectors

This file provides context for Claude Code when working in this repository.

## Architecture

Ports-and-adapters integration framework. Zero Django dependencies in the core package.

### Provider Families (6)

| Family | Port | Providers |
|--------|------|-----------|
| shop | `ShopPort` | CEL.ro, eMAG, Gomag, Okazii, PrestaShop, Trendyol, Vendigo, WooCommerce |
| courier | `CourierPort` | Colete Online, GLS, Sameday |
| payment | `PaymentPort` | Netopia, Stripe |
| messaging | `MessagingPort` | GoIP, RoboSMS, SMTP, Telegram, WhatsApp |
| storage | `StoragePort` | Dropbox, FTP, SFTP, S3, WebDAV |
| llm | `LLMPort` | OpenAI, Anthropic, Ollama, Gemini |

### Provider File Structure (7 files each)

```
providers/{family}/{provider}/
├── manifest.py    # ProviderManifest: auth, settings, capabilities, rate limits
├── client.py      # Raw HTTP calls only (uses ResilientHttpClient)
├── adapter.py     # Implements port interface + capabilities
├── mappers.py     # Converts between provider API ↔ framework DTOs
├── models.py      # Pydantic models for raw API payloads (NOT DTOs)
├── errors.py      # Maps provider errors to framework error hierarchy
└── __init__.py    # Auto-registers with global registry
```

### Key Patterns

- **Adapter __init__ signature:** `(credentials: dict, http_client=None, config=None, **kwargs)`
- **Settings flow:** `ProviderManifest.settings` → `Connection.config` JSONField → `registry.create_adapter(config=)` → adapter
- **StoragePort mirrors Django's Storage API:** save, open, delete, exists, listdir, size
- **MessagingPort.reply():** Concrete method that builds OutboundMessage with reply_to from InboundMessage
- **LLM platform-key fallback:** `api_key` credential is `required=False`, adapter checks `credentials.api_key` OR `config.platform_api_key`
- **Conditional registration:** SFTP and S3 providers only register if paramiko/boto3 are installed

### Optional Capabilities

EmbeddingCapability, TranscriptionCapability, StreamingCapability, ImageGenerationCapability, BulkUpdateCapability, BulkImportCapability, WebhookCapability, OAuthCapability, InvoiceAttachmentCapability, ProductFeedCapability

## Testing

### Unit tests (always run)

```bash
uv run --extra dev pytest tests/ -v
```

Integration tests are auto-skipped via `addopts = "-m 'not integration'"` in pyproject.toml.

### Integration tests (local Docker)

```bash
docker compose -f docker-compose.test.yml up -d
python scripts/setup_woocommerce.py  # one-time WooCommerce setup
uv run --extra dev --extra sftp --extra s3 pytest tests/ -v -m integration
docker compose -f docker-compose.test.yml down -v
```

### Test structure convention

```
tests/{family}/{provider}/test_integration.py
```

Each family has a `contract.py` with reusable tests that every provider must pass.

### Docker test services

| Service | Local port | Credentials |
|---------|-----------|-------------|
| MinIO (S3) | 19000 | minioadmin / minioadmin |
| FTP | 2121 | testuser / testpass |
| SFTP | 2222 | testuser / testpass |
| WebDAV | 8080 | testuser / testpass |
| WooCommerce | 8888 | ck_testkey123456789 / cs_testsecret123456789 |

## Build & CI

- **Build:** `uv` with hatchling backend
- **Extras:** `dev`, `sftp` (paramiko), `s3` (boto3), `oauth` (oauthlib)
- **CI:** GitLab — unit tests + ruff on every push, publish on tags
- **Pre-commit hook:** Auto-updates README.md providers table via `scripts/update_readme.py`

## Django Integration

Separate package at `packages/django/` (`django-bapp-connectors`). Provides abstract models (Connection, SyncState, ExecutionLog, WebhookEvent), services, Celery tasks, circuit breaker. Fully family-agnostic — no modifications needed for new families.

## Docs

- `docs/PROVIDER_GUIDE.md` — How to add a new provider
- `docs/DJANGO_INTEGRATION.md` — How to use the Django package
