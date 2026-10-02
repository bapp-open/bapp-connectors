"""
Verificarea JWS-urilor Apple (App Store Server Notifications V2 si App Store Server API).

Header-ul JWS poarta lantul `x5c`, care trebuie sa fie exact [leaf, intermediar, radacina]. Validam, in ordine
(aliniat cu app-store-server-library oficiala Apple):
  1. lantul are exact 3 certificate, iar al treilea e identic byte cu byte (DER) cu Apple Root CA - G3 inclus;
  2. toate cele 3 certificate sunt in perioada de valabilitate (ceasul local; fara OCSP/CRL);
  3. BasicConstraints: radacina si intermediarul au ca=True, leaf-ul ca=False (extensie lipsa = ca=False);
  4. leaf-ul poarta OID-ul Apple 1.2.840.113635.100.6.11.1, intermediarul 1.2.840.113635.100.6.2.1;
  5. leaf emis de intermediar si intermediar emis de radacina (nume + semnatura);
  6. semnatura ES256 a token-ului se verifica cu cheia publica a leaf-ului (alg=none si orice alt alg sunt respinse).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path

from bapp_connectors.providers.appstore.apple.errors import AppleWebhookError

APPLE_LEAF_OID = "1.2.840.113635.100.6.11.1"
APPLE_INTERMEDIATE_OID = "1.2.840.113635.100.6.2.1"

_ROOT_PATH = Path(__file__).parent / "certs" / "AppleRootCA-G3.pem"


def load_root_certificate() -> bytes:
    return _ROOT_PATH.read_bytes()


def _load_chain(x5c: list[str]):
    from cryptography import x509

    try:
        return [x509.load_der_x509_certificate(base64.b64decode(item)) for item in x5c]
    except Exception as exc:  # orice eroare de decodare DER/base64 devine AppleWebhookError
        raise AppleWebhookError(f"Lant x5c invalid: {exc}") from exc


def _is_ca(cert) -> bool:
    from cryptography import x509

    try:
        return cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        return False


def _has_oid(cert, oid: str) -> bool:
    from cryptography import x509

    try:
        cert.extensions.get_extension_for_oid(x509.ObjectIdentifier(oid))
    except x509.ExtensionNotFound:
        return False
    return True


def _verify_chain(chain, root_pem: bytes, now: datetime) -> None:
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
    from cryptography.hazmat.primitives.serialization import Encoding

    if len(chain) != 3:
        raise AppleWebhookError("Lantul x5c trebuie sa aiba exact 3 certificate")
    leaf, intermediate, chain_root = chain
    root = x509.load_pem_x509_certificate(root_pem)
    if chain_root.public_bytes(Encoding.DER) != root.public_bytes(Encoding.DER):
        raise AppleWebhookError("Radacina din x5c nu e Apple Root CA - G3")
    for cert in chain:
        if not (cert.not_valid_before_utc <= now <= cert.not_valid_after_utc):
            raise AppleWebhookError(f"Certificat in afara valabilitatii: {cert.subject.rfc4514_string()}")
    if not (_is_ca(root) and _is_ca(intermediate)) or _is_ca(leaf):
        raise AppleWebhookError("BasicConstraints invalid in lantul x5c (CA flag)")
    if not _has_oid(leaf, APPLE_LEAF_OID):
        raise AppleWebhookError("Leaf-ul nu poarta OID-ul Apple de semnare")
    if not _has_oid(intermediate, APPLE_INTERMEDIATE_OID):
        raise AppleWebhookError("Intermediarul nu poarta OID-ul Apple")
    for child, parent in ((leaf, intermediate), (intermediate, root)):
        try:
            child.verify_directly_issued_by(parent)
        except (InvalidSignature, UnsupportedAlgorithm, ValueError, TypeError) as exc:
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
