from bapp_connectors.core.capabilities import IssueManagementCapability, WebhookCapability
from bapp_connectors.core.ports import DevOpsPort
from bapp_connectors.providers.devops.gitlab.manifest import manifest


def test_manifest_identity():
    assert (manifest.name, manifest.family.value, manifest.allow_multiple) == ("gitlab", "devops", True)
    assert [f.name for f in manifest.auth.required_fields] == ["host", "token", "webhook_secret"]
    assert manifest.auth.required_fields[1].sensitive and not manifest.auth.required_fields[2].required
    assert manifest.webhooks.signature_method == "plain-token"
    assert manifest.webhooks.signature_header == "X-Gitlab-Token"


def test_manifest_endpoint_and_settings():
    host = manifest.auth.required_fields[0]
    assert host.role == "endpoint" and host.default == "gitlab.com"
    settings = {f.name: f.default for f in manifest.settings.fields}
    assert settings == {"verify_ssl": True, "timeout": 30, "groups": "", "include_archived": False}


def test_manifest_capabilities():
    assert manifest.capabilities == [DevOpsPort, IssueManagementCapability, WebhookCapability]
    assert "issue.commented" in manifest.webhooks.events
