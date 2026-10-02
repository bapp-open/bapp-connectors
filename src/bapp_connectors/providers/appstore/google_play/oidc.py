"""Verificarea token-ului OIDC pe care Pub/Sub il trimite in `Authorization: Bearer` la push."""

from __future__ import annotations

import time

from bapp_connectors.providers.appstore.google_play.errors import GooglePlayWebhookError

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})


class UnknownKeyIdError(GooglePlayWebhookError):
    """`kid`-ul token-ului nu e in JWKS (cheile Google se rotesc: merita o reincarcare)."""


def fetch_google_jwks(http_client, cache: dict | None = None, *, force: bool = False) -> dict:
    """JWKS-ul Google, cache-uit o ora in dict-ul dat (`{"jwks": ..., "fetched_at": ...}`)."""
    cache = cache if cache is not None else {}
    if not force and cache.get("jwks") and time.time() - cache.get("fetched_at", 0) < 3600:
        return cache["jwks"]
    # Endpoint public: clientul adapterului poarta auth-ul contului de serviciu, nu il trimitem la Google JWKS.
    jwks = http_client.call("GET", GOOGLE_JWKS_URL, headers={"Authorization": None})
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise GooglePlayWebhookError("JWKS Google invalid")
    cache["jwks"] = jwks
    cache["fetched_at"] = time.time()
    return jwks


def verify_google_id_token(token: str, *, audience: str, jwks: dict) -> dict:
    import jwt
    from jwt.algorithms import RSAAlgorithm

    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as exc:
        raise GooglePlayWebhookError(f"Token OIDC invalid: {exc}") from exc
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key_data is None:
        raise UnknownKeyIdError(f"Cheia {kid} nu e in JWKS-ul Google")
    try:
        claims = jwt.decode(
            token,
            RSAAlgorithm.from_jwk(key_data),
            algorithms=["RS256"],
            audience=audience,
            options={"require": ["exp", "iss", "aud"]},
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise GooglePlayWebhookError(f"Token OIDC respins: {exc}") from exc
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GooglePlayWebhookError(f"Issuer neasteptat: {claims.get('iss')}")
    return claims
