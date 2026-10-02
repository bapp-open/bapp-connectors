"""JWT ES256 pentru App Store Connect API si App Store Server API."""

from __future__ import annotations

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from bapp_connectors.providers.appstore.apple.auth import AppleJwtAuth, normalize_pem


@pytest.fixture(scope="module")
def key_pair():
    private = ec.generate_private_key(ec.SECP256R1())
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = private.public_key()
    return pem, public


def test_token_claims_and_header(key_pair):
    pem, public = key_pair
    now = [1_700_000_000.0]
    auth = AppleJwtAuth("ISSUER", "KEYID", pem, clock=lambda: now[0])
    token = auth.token()
    header = jwt.get_unverified_header(token)
    assert header["kid"] == "KEYID"
    assert header["alg"] == "ES256"
    # ceasul injectat e in 2023: expirarea fata de ceasul real nu se verifica aici
    claims = jwt.decode(
        token, public, algorithms=["ES256"], audience="appstoreconnect-v1", options={"verify_exp": False, "verify_iat": False}
    )
    assert claims["iss"] == "ISSUER"
    assert claims["exp"] - claims["iat"] == 1200
    assert "bid" not in claims


def test_server_api_token_has_bundle_id(key_pair):
    pem, public = key_pair
    auth = AppleJwtAuth("ISSUER", "KEYID", pem, bundle_id="ro.cbsoft.app")
    claims = jwt.decode(auth.token(), public, algorithms=["ES256"], audience="appstoreconnect-v1")
    assert claims["bid"] == "ro.cbsoft.app"


def test_token_is_cached_then_regenerated_near_expiry(key_pair):
    pem, _ = key_pair
    now = [1_700_000_000.0]
    auth = AppleJwtAuth("I", "K", pem, clock=lambda: now[0])
    first = auth.token()
    now[0] += 100
    assert auth.token() == first
    now[0] += 1200 - 100 - 30  # la 30 s de expirare
    assert auth.token() != first


def test_private_key_with_escaped_newlines(key_pair):
    pem, public = key_pair
    escaped = pem.replace("\n", "\\n")
    auth = AppleJwtAuth("I", "K", escaped)
    jwt.decode(auth.token(), public, algorithms=["ES256"], audience="appstoreconnect-v1")


def test_apply_to_headers_sets_bearer(key_pair):
    pem, _ = key_pair
    auth = AppleJwtAuth("I", "K", pem)
    headers = auth.apply_to_headers({})
    assert headers["Authorization"].startswith("Bearer ")


def test_normalize_pem():
    assert normalize_pem("  a\\nb\\n ") == "a\nb"
