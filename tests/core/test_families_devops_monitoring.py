from bapp_connectors.core.dto.webhook import WebhookEventType
from bapp_connectors.core.types import ProviderFamily
from bapp_connectors.core.webhooks import ADAPTER_VERIFIED_METHODS, AdapterOnlyVerifier, get_verifier


def test_families_exist():
    assert ProviderFamily.DEVOPS == "devops"
    assert ProviderFamily.MONITORING == "monitoring"


def test_webhook_event_types():
    assert WebhookEventType.ISSUE_OPENED == "issue.opened"
    assert WebhookEventType.PIPELINE_FAILED == "pipeline.failed"
    assert WebhookEventType.REPOSITORY_PUSH == "repository.push"
    assert WebhookEventType.ERROR_ISSUE_RESOLVED == "error_issue.resolved"


def test_plain_token_is_adapter_verified():
    assert "plain-token" in ADAPTER_VERIFIED_METHODS
    assert isinstance(get_verifier("plain-token"), AdapterOnlyVerifier)
