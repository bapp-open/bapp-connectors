"""Manifestul Google Play."""

from bapp_connectors.core.capabilities import FinancialCapability, WebhookCapability
from bapp_connectors.core.manifest import (
    AuthConfig,
    CredentialField,
    ProviderManifest,
    RateLimitConfig,
    RetryConfig,
    WebhookConfig,
)
from bapp_connectors.core.ports import AppStorePort
from bapp_connectors.core.types import AuthStrategy, BackoffStrategy, ProviderFamily

manifest = ProviderManifest(
    name="google_play",
    family=ProviderFamily.APPSTORE,
    display_name="Google Play",
    description="Google Play Console: rapoarte de venituri si vanzari din bucket-ul Cloud Storage, recenzii cu raspuns, "
    "cumparaturi anulate, abonamente si notificari in timp real (Pub/Sub).",
    base_url="https://storage.googleapis.com/storage/v1/",
    allow_multiple=True,
    auth=AuthConfig(
        strategy=AuthStrategy.CUSTOM,
        required_fields=[
            CredentialField(name="service_account_json", label="Service account (JSON)", sensitive=True, help_text="Cheia JSON a service account-ului; contul trebuie invitat in Play Console cu „View financial data” si „Reply to reviews”."),
            CredentialField(name="bucket_uri", label="Cloud Storage URI", role="endpoint", help_text="Play Console > Download reports > „Copy Cloud Storage URI” (gs://pubsite_prod_rev_...)."),
            CredentialField(name="package_names", label="Pachete (package names)", required=False, help_text="Separate prin virgula. Necesare pentru recenzii live, cumparaturi anulate si abonamente."),
            CredentialField(name="pubsub_audience", label="Audience OIDC Pub/Sub", required=False, help_text="Daca push-ul Pub/Sub trimite token OIDC, audience-ul configurat; gol = push-ul e acceptat FARA verificare. Setat fara pubsub_service_account_email = toate notificarile sunt respinse."),
            CredentialField(name="pubsub_service_account_email", label="Cont de serviciu OIDC Pub/Sub", required=False, help_text="Contul de serviciu cu care subscriptia push semneaza tokenul OIDC; obligatoriu cand pubsub_audience e setat."),
        ],
    ),
    capabilities=[AppStorePort, FinancialCapability, WebhookCapability],
    rate_limit=RateLimitConfig(requests_per_second=2.0, burst=10),
    retry=RetryConfig(max_retries=3, backoff=BackoffStrategy.EXPONENTIAL, non_retryable_status_codes=[400, 401, 403, 404]),
    webhooks=WebhookConfig(supported=True, signature_method="google-pubsub-oidc", signature_header="Authorization", events=["subscriptionNotification", "voidedPurchaseNotification", "oneTimeProductNotification"]),
)
