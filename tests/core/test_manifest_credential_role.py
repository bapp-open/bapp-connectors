from bapp_connectors.core.manifest import CredentialField


def test_credential_field_role_defaults_to_none():
    assert CredentialField(name="api_key").role is None


def test_woocommerce_domain_is_the_endpoint_credential():
    from bapp_connectors.providers.shop.woocommerce.manifest import manifest

    by_name = {f.name: f for f in manifest.auth.required_fields}
    assert by_name["domain"].role == "endpoint"
    oauth_by_name = {f.name: f for f in manifest.auth.oauth.credential_fields}
    assert oauth_by_name["domain"].role == "endpoint"
    assert by_name["consumer_key"].role is None
