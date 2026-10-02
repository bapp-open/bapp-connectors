"""Service account JWT (RS256) -> access token, cu cache."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from bapp_connectors.core.errors import AuthenticationError, ConfigurationError, ProviderError
from bapp_connectors.providers.appstore.google_play.auth import (
    TOKEN_URI,
    GoogleServiceAccountAuth,
    _default_token_fetcher,
    bucket_name_from_uri,
    parse_service_account,
)

SCOPES = ["https://www.googleapis.com/auth/devstorage.read_only", "https://www.googleapis.com/auth/androidpublisher"]


@pytest.fixture(scope="module")
def service_account():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    return {
        "type": "service_account",
        "client_email": "bapp@project.iam.gserviceaccount.com",
        "private_key": pem,
        "token_uri": "https://oauth2.googleapis.com/token",
    }, key.public_key()


def test_assertion_claims_and_exchange(service_account):
    sa, public = service_account
    seen = {}

    def fetcher(token_uri, assertion):
        seen["uri"] = token_uri
        seen["claims"] = jwt.decode(assertion, public, algorithms=["RS256"], audience=sa["token_uri"], options={"verify_exp": False, "verify_iat": False})
        return {"access_token": "ya29.x", "expires_in": 3600}

    auth = GoogleServiceAccountAuth(sa, SCOPES, token_fetcher=fetcher, clock=lambda: 1_700_000_000.0)
    assert auth.access_token() == "ya29.x"
    assert seen["uri"] == sa["token_uri"]
    assert seen["claims"]["iss"] == sa["client_email"]
    assert seen["claims"]["scope"] == " ".join(SCOPES)
    assert seen["claims"]["exp"] - seen["claims"]["iat"] == 3600
    assert auth.apply_to_headers({})["Authorization"] == "Bearer ya29.x"


def test_token_cached_until_near_expiry(service_account):
    sa, _ = service_account
    now = [1_700_000_000.0]
    calls = []

    def fetcher(token_uri, assertion):
        calls.append(1)
        return {"access_token": f"t{len(calls)}", "expires_in": 3600}

    auth = GoogleServiceAccountAuth(sa, SCOPES, token_fetcher=fetcher, clock=lambda: now[0])
    assert auth.access_token() == "t1"
    now[0] += 3000
    assert auth.access_token() == "t1"
    now[0] += 600
    assert auth.access_token() == "t2"


def test_parse_service_account_from_text_with_escaped_key(service_account):
    sa, _ = service_account
    text = json.dumps({**sa, "private_key": sa["private_key"].replace("\n", "\\n")})
    parsed = parse_service_account(text)
    assert parsed["private_key"].startswith("-----BEGIN PRIVATE KEY-----\n")


def test_parse_service_account_missing_fields():
    with pytest.raises(ConfigurationError):
        parse_service_account('{"type": "service_account"}')


def test_bucket_name_from_uri():
    assert bucket_name_from_uri("gs://pubsite_prod_rev_123/") == "pubsite_prod_rev_123"
    assert bucket_name_from_uri("pubsite_prod_rev_123") == "pubsite_prod_rev_123"


def test_default_fetcher_maps_invalid_grant_to_authentication_error():
    fake = SimpleNamespace(ok=False, status_code=400, text='{"error":"invalid_grant"}')
    with patch("requests.post", return_value=fake), pytest.raises(AuthenticationError):
        _default_token_fetcher(TOKEN_URI, "assertion")


def test_default_fetcher_wraps_connection_error():
    with patch("requests.post", side_effect=requests.ConnectionError("boom")), pytest.raises(ProviderError):
        _default_token_fetcher(TOKEN_URI, "assertion")
