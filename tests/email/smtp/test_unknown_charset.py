"""A message declaring a charset Python does not know used to fail the whole folder fetch
with ``LookupError: unknown encoding: unknown-8bit``."""

from __future__ import annotations

from email import message_from_bytes

from bapp_connectors.providers.email.smtp.client import _decode_bytes, _decode_header_value
from bapp_connectors.providers.email.smtp.mappers import message_to_detail


def test_raw_8bit_header_is_decoded():
    # what the stdlib yields for a Subject carrying raw non-ASCII bytes
    message = message_from_bytes("Subject: Factură nr. 5\n\nbody".encode())

    assert _decode_header_value(message["Subject"]) == "Factură nr. 5"


def test_unknown_charset_falls_back_to_utf8_then_latin1():
    assert _decode_bytes("Factură".encode(), "unknown-8bit") == "Factură"
    assert _decode_bytes(b"Factur\xe3", "x-invented") == "Facturã"


def test_known_charset_is_still_honoured():
    assert _decode_bytes("Factură".encode("iso-8859-2"), "iso-8859-2") == "Factură"


def test_body_with_an_unknown_charset_is_read():
    raw = b'Content-Type: text/plain; charset="unknown-8bit"\nSubject: x\n\nFactur\xc4\x83 5'

    detail = message_to_detail("1", message_from_bytes(raw), "INBOX")

    assert detail.text_body.strip() == "Factură 5"
