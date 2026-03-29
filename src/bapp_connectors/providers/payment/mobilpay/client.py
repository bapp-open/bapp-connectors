"""
MobilPay payment client.

MobilPay uses RSA+ARC4 encryption for XML payment requests.
Flow: build XML → encrypt with public cert → POST form → receive encrypted IPN → decrypt with private key.

Dependencies: cryptography, pyopenssl.
"""

from __future__ import annotations

import base64
import logging
import os
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote
from xml.dom.minidom import Document, parseString

from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
from cryptography.hazmat.primitives.ciphers import Cipher

try:
    from cryptography.hazmat.decrepit.ciphers.algorithms import ARC4
except ImportError:
    from cryptography.hazmat.primitives.ciphers.algorithms import ARC4
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from OpenSSL import crypto

logger = logging.getLogger(__name__)


# ── Crypto helpers ──


def _get_rsa_public_key(public_cert_pem: str):
    """Extract RSA public key from X509 PEM certificate."""
    cert = crypto.load_certificate(crypto.FILETYPE_PEM, public_cert_pem.encode())
    pub_key_pem = crypto.dump_publickey(crypto.FILETYPE_PEM, cert.get_pubkey())
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    return load_pem_public_key(pub_key_pem)


def _get_rsa_private_key(private_key_pem: str, password: bytes | None = None):
    """Load RSA private key from PEM string."""
    return load_pem_private_key(private_key_pem.encode(), password=password)


def encrypt_xml(xml_bytes: bytes, public_cert_pem: str) -> tuple[str, str]:
    """Encrypt XML data using RSA+ARC4.

    Returns (enc_data_b64, env_key_b64).
    """
    public_key = _get_rsa_public_key(public_cert_pem)

    # Generate random 16-byte symmetric key
    random_key = os.urandom(16)

    # RSA-encrypt the symmetric key with PKCS1v15 padding
    enc_key = public_key.encrypt(random_key, rsa_padding.PKCS1v15())

    # ARC4-encrypt the XML data with the symmetric key
    cipher = Cipher(ARC4(random_key), mode=None)
    encryptor = cipher.encryptor()
    enc_data = encryptor.update(xml_bytes) + encryptor.finalize()

    return base64.b64encode(enc_data).decode(), base64.b64encode(enc_key).decode()


def decrypt_xml(enc_data_b64: str, env_key_b64: str, private_key_pem: str) -> bytes:
    """Decrypt RSA+ARC4 encrypted data.

    Returns decrypted XML bytes.
    """
    private_key = _get_rsa_private_key(private_key_pem)
    enc_data = base64.b64decode(enc_data_b64)
    enc_key = base64.b64decode(env_key_b64)

    # RSA-decrypt the symmetric key
    decrypted_key = private_key.decrypt(enc_key, rsa_padding.PKCS1v15())

    # ARC4-decrypt the XML data
    cipher = Cipher(ARC4(decrypted_key), mode=None)
    decryptor = cipher.decryptor()
    return decryptor.update(enc_data) + decryptor.finalize()


# ── XML builders ──


def build_order_xml(
    *,
    client_key: str,
    order_id: str,
    amount: Decimal,
    currency: str,
    description: str,
    confirm_url: str,
    return_url: str,
    client_name: str = "",
    client_email: str = "",
    client_phone: str = "",
    client_address: str = "",
    is_company: bool = False,
) -> bytes:
    """Build MobilPay XML order document."""
    doc = Document()

    order = doc.createElement("order")
    order.setAttribute("type", "card")
    order.setAttribute("id", str(order_id))
    order.setAttribute("timestamp", datetime.now(UTC).strftime("%Y%m%d%H%M%S"))

    # Signature
    sig_elem = doc.createElement("signature")
    sig_elem.appendChild(doc.createTextNode(client_key))
    order.appendChild(sig_elem)

    # Invoice
    invoice = doc.createElement("invoice")
    invoice.setAttribute("currency", currency)
    invoice.setAttribute("amount", f"{amount:.2f}")

    if description:
        details = doc.createElement("details")
        details.appendChild(doc.createCDATASection(quote(description, encoding="utf-8")))
        invoice.appendChild(details)

    # Contact info
    contact_info = doc.createElement("contact_info")
    billing = doc.createElement("billing")
    billing.setAttribute("type", "company" if is_company else "person")

    for tag, value in [
        ("first_name", client_name),
        ("address", client_address),
        ("email", client_email),
        ("mobile_phone", client_phone),
    ]:
        if value:
            elem = doc.createElement(tag)
            elem.appendChild(doc.createCDATASection(quote(value, encoding="utf-8")))
            billing.appendChild(elem)

    contact_info.appendChild(billing)
    invoice.appendChild(contact_info)
    order.appendChild(invoice)

    # URLs
    url_elem = doc.createElement("url")
    ret = doc.createElement("return")
    ret.appendChild(doc.createTextNode(return_url))
    url_elem.appendChild(ret)
    conf = doc.createElement("confirm")
    conf.appendChild(doc.createTextNode(confirm_url))
    url_elem.appendChild(conf)
    order.appendChild(url_elem)

    doc.appendChild(order)
    return doc.toprettyxml(indent="\t", newl="\n", encoding="utf-8")


# ── IPN parsing ──


def parse_ipn_xml(xml_bytes: bytes) -> dict:
    """Parse decrypted MobilPay IPN XML and extract relevant fields.

    Returns dict with: order_id, signature, error_code, error_message, action, crc,
    and any additional notify fields.
    """
    doc = parseString(xml_bytes)

    result: dict = {}

    # Order element
    orders = doc.getElementsByTagName("order")
    if not orders:
        return result

    order = orders[0]
    result["order_id"] = order.getAttribute("id")

    # Signature
    sigs = order.getElementsByTagName("signature")
    if sigs and sigs[0].firstChild:
        result["signature"] = sigs[0].firstChild.nodeValue

    # Notify element (mobilpay)
    notifies = order.getElementsByTagName("mobilpay")
    if notifies:
        notify = notifies[0]
        result["crc"] = notify.getAttribute("crc")

        # Action
        actions = notify.getElementsByTagName("action")
        if actions and actions[0].firstChild:
            result["action"] = actions[0].firstChild.nodeValue

        # Error
        errors = notify.getElementsByTagName("error")
        if errors:
            error_elem = errors[0]
            result["error_code"] = error_elem.getAttribute("code")
            if error_elem.firstChild:
                result["error_message"] = error_elem.firstChild.nodeValue

        # Purchase ID
        purchases = notify.getElementsByTagName("purchase")
        if purchases and purchases[0].firstChild:
            result["purchase_id"] = purchases[0].firstChild.nodeValue

        # Processed amount
        amounts = notify.getElementsByTagName("processed_amount")
        if amounts and amounts[0].firstChild:
            result["processed_amount"] = amounts[0].firstChild.nodeValue

        # Pan masked
        pans = notify.getElementsByTagName("pan_masked")
        if pans and pans[0].firstChild:
            result["pan_masked"] = pans[0].firstChild.nodeValue

        # Token
        tokens = notify.getElementsByTagName("token_id")
        if tokens and tokens[0].firstChild:
            result["token_id"] = tokens[0].firstChild.nodeValue

    # Invoice
    invoices = order.getElementsByTagName("invoice")
    if invoices:
        inv = invoices[0]
        result["currency"] = inv.getAttribute("currency")
        result["amount"] = inv.getAttribute("amount")

    return result
