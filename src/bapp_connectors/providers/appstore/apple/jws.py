"""
Verificarea JWS-urilor Apple (App Store Server Notifications V2 si App Store Server API).

Header-ul JWS poarta lantul `x5c` (leaf, intermediar, radacina). Validam:
  1. fiecare certificat e semnat de urmatorul din lant, iar ultimul e identic cu Apple Root CA - G3;
  2. toate certificatele sunt in perioada de valabilitate;
  3. semnatura ES256 a token-ului se verifica cu cheia publica a leaf-ului.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from bapp_connectors.providers.appstore.apple.errors import AppleWebhookError

_ROOT_PATH = Path(__file__).parent / "certs" / "AppleRootCA-G3.pem"


def load_root_certificate() -> bytes:
    return _ROOT_PATH.read_bytes()


def _load_chain(x5c: list[str]):
    from cryptography import x509

    try:
        return [x509.load_der_x509_certificate(base64.b64decode(item)) for item in x5c]
    except Exception as exc:  # orice eroare de decodare DER/base64 devine AppleWebhookError
        raise AppleWebhookError(f"Lant x5c invalid: {exc}") from exc


def _verify_chain(chain, root_pem: bytes, now: datetime) -> None:
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.serialization import Encoding

    if not chain:
        raise AppleWebhookError("Lipseste lantul x5c")
    root = x509.load_pem_x509_certificate(root_pem)
    for cert in chain:
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise AppleWebhookError(f"Certificat in afara valabilitatii: {cert.subject.rfc4514_string()}")
    # Lantul se termina fie cu radacina insasi, fie cu un intermediar emis de ea.
    anchored = chain[-1].public_bytes(Encoding.DER) == root.public_bytes(Encoding.DER)
    links = list(chain) if anchored else [*chain, root]
    for child, parent in pairwise(links):
        try:
            child.verify_directly_issued_by(parent)
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise AppleWebhookError(
                f"Certificatul {child.subject.rfc4514_string()} nu e emis de {parent.subject.rfc4514_string()}"
            ) from exc


def decode_signed_payload(token: str, *, root_pem: bytes | None = None, now: datetime | None = None) -> dict:
    import jwt

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AppleWebhookError(f"JWS invalid: {exc}") from exc
    chain = _load_chain(header.get("x5c") or [])
    _verify_chain(chain, root_pem or load_root_certificate(), now or datetime.now(UTC))
    try:
        return jwt.decode(token, chain[0].public_key(), algorithms=["ES256"], options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise AppleWebhookError(f"Semnatura JWS nu se verifica: {exc}") from exc
