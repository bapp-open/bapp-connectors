"""Inspect serialized SMTP submissions without ever contacting a mail server."""

from __future__ import annotations

import smtplib
from email import policy
from email.parser import Parser
from unittest.mock import MagicMock, patch

import pytest

from bapp_connectors.core.dto import DeliveryStatus, OutboundMessage
from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.client import SMTPClient

CREDS = {
    "host": "smtp.example.test",
    "username": "john.doe@example.test",
    "password": "test-password",
    "from_email": "comenzi@example.test",
    "from_name": "Comenzi România",
    "imap_enabled": "false",
}
PARENT = "<parent@example.test>"
ROOT = "<root@example.test>"
ATTACHMENTS = [
    {"filename": "factură-șț.pdf", "content": b"%PDF-1.4\x00\xff", "content_type": "application/pdf"},
    {"filename": "logo.png", "content": b"\x89PNG\r\n\x1a\n", "content_type": "image/png"},
    {"filename": "tabel.csv", "content": b"a,b\r\n1,2\r\n", "content_type": "text/csv; charset=utf-8"},
]


@pytest.fixture
def transport():
    connection = MagicMock()
    connection.sendmail.return_value = {}
    with (
        patch("bapp_connectors.providers.email.smtp.client.smtplib.SMTP", return_value=connection) as smtp,
        patch("bapp_connectors.providers.email.smtp.client.smtplib.SMTP_SSL", return_value=connection) as smtp_ssl,
    ):
        yield connection, smtp, smtp_ssl


@pytest.fixture
def adapter(transport):
    return SMTPEmailAdapter(dict(CREDS))


def message(**kwargs):
    defaults = {"channel": "email", "to": "recipient@example.test", "subject": "Răspuns comandă"}
    return OutboundMessage(**(defaults | kwargs))


def submitted(transport):
    sender, recipients, raw = transport[0].sendmail.call_args.args
    # smtplib.sendmail encodes a str as ASCII; Unicode belongs in MIME encodings.
    raw.encode("ascii")
    assert "\r\n" in raw
    parsed = Parser(policy=policy.default).parsestr(raw)
    for part in parsed.walk():
        assert not part.defects
        for header in part.values():
            assert not header.defects
    return sender, recipients, parsed


@pytest.mark.parametrize(
    ("body", "html", "with_attachments", "outer_type", "body_types"),
    [
        ("Salut șț", "", False, "text/plain", ["text/plain"]),
        ("", "<p>Salut șț</p>", False, "text/html", ["text/html"]),
        ("Salut șț", "<p>Salut șț</p>", False, "multipart/alternative", ["text/plain", "text/html"]),
        ("Salut șț", "", True, "multipart/mixed", ["text/plain"]),
        ("", "<p>Salut șț</p>", True, "multipart/mixed", ["text/html"]),
        ("Salut șț", "<p>Salut șț</p>", True, "multipart/mixed", ["text/plain", "text/html"]),
        ("", "", True, "multipart/mixed", []),
        ("", "", False, "text/plain", ["text/plain"]),
    ],
)
def test_mime_structure_and_attachment_metadata(
    adapter, transport, body, html, with_attachments, outer_type, body_types
):
    attachments = ATTACHMENTS if with_attachments else []
    outbound = message(body=body, html_body=html, attachments=attachments)
    report = adapter.send(outbound)

    assert report.status == DeliveryStatus.SENT
    assert report.error == ""
    assert report.delivered_at is None
    assert outbound.message_id == ""  # Sending does not mutate the caller's DTO.
    _sender, _recipients, mime = submitted(transport)
    assert str(mime["Subject"]) == outbound.subject
    assert mime["MIME-Version"] == "1.0"
    assert mime["Date"]
    assert len(mime.get_all("Message-ID")) == 1
    assert str(mime["Message-ID"]) == report.message_id == report.extra["rfc_message_id"]
    assert report.message_id.startswith("<") and report.message_id.endswith(">")
    assert mime.get_content_type() == outer_type

    body_parts = [
        part for part in mime.walk() if not part.is_multipart() and part.get_content_disposition() != "attachment"
    ]
    assert [part.get_content_type() for part in body_parts] == body_types
    for part in body_parts:
        expected = html if part.get_content_subtype() == "html" else body
        assert part.get_content().rstrip("\r\n") == expected
    if with_attachments:
        children = list(mime.iter_parts())
        assert len(children) == len(attachments) + bool(body_types)
        if len(body_types) == 2:
            assert children[0].get_content_type() == "multipart/alternative"
            assert [part.get_content_type() for part in children[0].iter_parts()] == body_types
    parts = list(mime.iter_attachments())
    assert len(parts) == len(attachments)
    for part, attachment in zip(parts, attachments, strict=True):
        assert part.get_content_disposition() == "attachment"
        assert part.get_filename() == attachment["filename"]
        assert part.get_content_type() == attachment["content_type"].split(";")[0]
        assert part.get_payload(decode=True) == attachment["content"]
        assert part["Content-Transfer-Encoding"] == "base64"
    if attachments:
        assert parts[-1].get_content_charset() == "utf-8"
    transport[0].quit.assert_called_once_with()


@pytest.mark.parametrize(
    "correlation_id", ["order-123", "7c317455-3fd8-4ae5-928a-9dd24c02206b", "<local@example.test>"]
)
@pytest.mark.parametrize("explicit_id", ["", "<outgoing@example.test>"])
def test_caller_correlation_id_is_preserved_separately_from_rfc_id(adapter, transport, correlation_id, explicit_id):
    outbound = message(message_id=correlation_id, body="Reply", extra={"rfc_message_id": explicit_id})
    report = adapter.send(outbound)
    assert report.status == DeliveryStatus.SENT
    assert report.message_id == correlation_id
    rfc_id = str(submitted(transport)[2]["Message-ID"])
    assert rfc_id == report.extra["rfc_message_id"]
    if explicit_id:
        assert rfc_id == explicit_id
    else:
        assert rfc_id != correlation_id


def test_explicit_rfc_id_is_returned_when_correlation_id_is_absent(adapter, transport):
    report = adapter.send(message(extra={"rfc_message_id": "<chosen@example.test>"}))
    assert report.status == DeliveryStatus.SENT
    assert report.message_id == report.extra["rfc_message_id"] == str(submitted(transport)[2]["Message-ID"])
    assert report.message_id == "<chosen@example.test>"


@pytest.mark.parametrize("references", [None, [], "", [ROOT], ROOT, [ROOT, PARENT], f"{ROOT} {PARENT}"])
def test_reply_preserves_references_chain_and_appends_parent(adapter, transport, references):
    outbound = message(body="Reply", reply_to=PARENT, extra={"references": references})
    report = adapter.send(outbound)
    assert report.status == DeliveryStatus.SENT
    mime = submitted(transport)[2]
    assert str(mime["In-Reply-To"]) == PARENT
    expected = [ROOT, PARENT] if references else [PARENT]
    assert str(mime["References"]).split() == expected
    assert mime["Reply-To"] is None
    assert outbound.extra["references"] == references


def test_reply_address_and_references_without_parent(adapter, transport):
    report = adapter.send(message(extra={"reply_to": "Support <support@example.test>", "references": [ROOT]}))
    assert report.status == DeliveryStatus.SENT
    mime = submitted(transport)[2]
    assert str(mime["Reply-To"]) == "Support <support@example.test>"
    assert mime["In-Reply-To"] is None
    assert str(mime["References"]) == ROOT


def test_long_reference_chain_and_unicode_filename_survive_header_folding(adapter, transport):
    references = [f"<ancestor-{index:03d}@example.test>" for index in range(50)]
    filename = "factură-șț-" * 20 + ".pdf"
    report = adapter.send(
        message(
            body="Reply",
            reply_to=PARENT,
            extra={"references": references},
            attachments=[{**ATTACHMENTS[0], "filename": filename}],
        )
    )
    assert report.status == DeliveryStatus.SENT
    mime = submitted(transport)[2]
    assert str(mime["References"]).split() == [*references, PARENT]
    assert next(mime.iter_attachments()).get_filename() == filename
    assert report.extra["rfc_message_id"] == str(mime["Message-ID"])


def test_reply_address_is_independent_of_parent_id(adapter, transport):
    report = adapter.send(message(reply_to=PARENT, extra={"reply_to": "support@example.test"}))
    assert report.status == DeliveryStatus.SENT
    mime = submitted(transport)[2]
    assert str(mime["In-Reply-To"]) == PARENT
    assert str(mime["Reply-To"]) == "support@example.test"


@pytest.mark.parametrize("ssl", [False, True])
@pytest.mark.parametrize(
    ("credential_sender", "extra", "expected_sender", "expected_name"),
    [
        ("comenzi@example.test", {}, "comenzi@example.test", "Comenzi România"),
        (
            "comenzi@example.test",
            {"from_email": "support@example.test", "from_name": "Support"},
            "support@example.test",
            "Support",
        ),
        ("comenzi@example.test", {"from_email": "", "from_name": ""}, "comenzi@example.test", "Comenzi România"),
        ("", {}, "john.doe@example.test", "Comenzi România"),
        ("", {"from_email": "comenzi@example.test"}, "comenzi@example.test", "Comenzi România"),
    ],
)
def test_sender_precedence_and_authentication_are_independent(
    transport, ssl, credential_sender, extra, expected_sender, expected_name
):
    adapter = SMTPEmailAdapter({**CREDS, "from_email": credential_sender, "use_ssl": str(ssl).lower()})
    report = adapter.send(message(body="Salut", extra=extra))
    assert report.status == DeliveryStatus.SENT
    sender, recipients, mime = submitted(transport)
    assert sender == expected_sender
    assert recipients == ["recipient@example.test"]
    assert mime["From"].addresses[0].addr_spec == expected_sender
    assert mime["From"].addresses[0].display_name == expected_name
    transport[0].login.assert_called_once_with("john.doe@example.test", CREDS["password"])
    if ssl:
        transport[2].assert_called_once_with(CREDS["host"], 587, timeout=30)
        transport[1].assert_not_called()
        transport[0].starttls.assert_not_called()
    else:
        transport[1].assert_called_once_with(CREDS["host"], 587, timeout=30)
        transport[2].assert_not_called()
        transport[0].starttls.assert_called_once_with()


def test_cc_bcc_envelope_and_attachment_defaults(adapter, transport):
    report = adapter.send(
        message(
            body="text",
            extra={"cc": ["cc@example.test"], "bcc": ["bcc@example.test"]},
            attachments=[{"content": b"data"}],
        )
    )
    assert report.status == DeliveryStatus.SENT
    _sender, recipients, mime = submitted(transport)
    assert recipients == ["recipient@example.test", "cc@example.test", "bcc@example.test"]
    assert str(mime["Cc"]) == "cc@example.test"
    assert mime["Bcc"] is None
    attachment = next(mime.iter_attachments())
    assert attachment.get_filename() == "attachment"
    assert attachment.get_content_type() == "application/octet-stream"
    assert attachment.get_payload(decode=True) == b"data"


@pytest.mark.parametrize(
    "invalid_id",
    [
        "internal-id",
        "plain@example.test",
        "<missing-end@example.test",
        "<a@example.test> <b@example.test>",
        "<a..b@example.test>",
        "<ü@example.test>",
        "   ",
        "<ok@example.test>\r\nBcc: injected@example.test",
    ],
)
@pytest.mark.parametrize("field", ["rfc_message_id", "parent", "references"])
def test_invalid_rfc_ids_fail_before_connecting(adapter, transport, field, invalid_id):
    kwargs = (
        {"reply_to": invalid_id}
        if field == "parent"
        else {"extra": {field: [invalid_id] if field == "references" else invalid_id}}
    )
    report = adapter.send(message(message_id="local-id", **kwargs))
    assert report.status == DeliveryStatus.FAILED
    assert report.message_id == "local-id"
    assert report.error
    transport[1].assert_not_called()
    transport[2].assert_not_called()
    transport[0].sendmail.assert_not_called()


@pytest.mark.parametrize("references", [[""], [None], 123, [ROOT, "invalid"], f"{ROOT}\r\nBcc: injected@example.test"])
def test_invalid_reference_chain_is_not_silently_discarded(adapter, transport, references):
    report = adapter.send(message(reply_to=PARENT, extra={"references": references}))
    assert report.status == DeliveryStatus.FAILED
    assert report.error
    transport[1].assert_not_called()


@pytest.mark.parametrize(
    "injection", ["\r\nBcc: injected@example.test", "\nX-Injected: yes", "\rX-Injected: yes", "\x00"]
)
@pytest.mark.parametrize(
    "field", ["subject", "to", "from_email", "from_name", "cc", "bcc", "reply_to", "filename", "content_type"]
)
def test_header_injection_is_rejected_before_connecting(adapter, transport, injection, field):
    if field in ("subject", "to"):
        kwargs = {field: f"value{injection}"}
    elif field in ("filename", "content_type"):
        kwargs = {"attachments": [{**ATTACHMENTS[0], field: f"value{injection}"}]}
    else:
        value = [f"value{injection}"] if field in ("cc", "bcc") else f"value{injection}"
        kwargs = {"extra": {field: value}}
    report = adapter.send(message(body="text", **kwargs))
    assert report.status == DeliveryStatus.FAILED
    assert report.error
    transport[1].assert_not_called()
    transport[2].assert_not_called()


@pytest.mark.parametrize("content_type", ["invalid", "application/", 'image/png; name="unterminated'])
def test_invalid_attachment_content_type_fails_before_connecting(adapter, transport, content_type):
    report = adapter.send(message(attachments=[{**ATTACHMENTS[0], "content_type": content_type}]))
    assert report.status == DeliveryStatus.FAILED
    assert report.error
    transport[1].assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
def test_recipient_refusals_are_reported_with_wire_id_and_details(adapter, transport, partial):
    refused = {"recipient@example.test": (550, b"Mailbox unavailable")}
    if partial:
        transport[0].sendmail.return_value = refused
    else:
        transport[0].sendmail.side_effect = smtplib.SMTPRecipientsRefused(refused)
    report = adapter.send(message(message_id="local-id", body="text", extra={"cc": ["cc@example.test"]}))
    assert report.message_id == "local-id"
    assert report.status == DeliveryStatus.FAILED
    assert "550" in report.error and "Mailbox unavailable" in report.error
    assert report.extra["rfc_message_id"] == str(submitted(transport)[2]["Message-ID"])
    assert report.extra["refused_recipients"] == {
        "recipient@example.test": {"code": 550, "message": "Mailbox unavailable"}
    }
    assert report.delivered_at is None
    transport[0].quit.assert_called_once_with()


@pytest.mark.parametrize("correlation_id", ["", "local-id"])
def test_data_rejection_preserves_correlation(adapter, transport, correlation_id):
    transport[0].sendmail.side_effect = smtplib.SMTPDataError(554, b"Message rejected")
    report = adapter.send(message(message_id=correlation_id, body="text"))
    rfc_id = str(submitted(transport)[2]["Message-ID"])
    assert report.status == DeliveryStatus.FAILED
    assert report.message_id == (correlation_id or rfc_id)
    assert report.extra["rfc_message_id"] == rfc_id
    assert "554" in report.error and "Message rejected" in report.error
    transport[0].quit.assert_called_once_with()


@pytest.mark.parametrize("stage", ["connect", "login", "sender"])
def test_transport_errors_remain_failed(adapter, transport, stage):
    if stage == "connect":
        transport[1].side_effect = OSError("SMTP connection failed")
    elif stage == "login":
        transport[0].login.side_effect = smtplib.SMTPAuthenticationError(535, b"Authentication failed")
    else:
        transport[0].sendmail.side_effect = smtplib.SMTPSenderRefused(
            553, b"Alias not permitted", "comenzi@example.test"
        )
    report = adapter.send(message(message_id="local-id", body="text"))
    assert report.status == DeliveryStatus.FAILED
    assert report.message_id == "local-id"
    assert report.extra["rfc_message_id"]
    assert report.error


def test_quit_error_does_not_override_smtp_acceptance(adapter, transport):
    transport[0].quit.side_effect = smtplib.SMTPServerDisconnected("Already closed")
    report = adapter.send(message(body="text"))
    assert report.status == DeliveryStatus.SENT
    assert not report.error


def test_bulk_generates_distinct_wire_ids_and_preserves_each_report(adapter, transport):
    transport[0].sendmail.side_effect = [{}, smtplib.SMTPDataError(554, b"Rejected"), {}]
    reports = adapter.send_bulk(
        [message(body="one"), message(message_id="local-id", body="two"), message(body="three")]
    )
    assert [report.status for report in reports] == [DeliveryStatus.SENT, DeliveryStatus.FAILED, DeliveryStatus.SENT]
    ids = [
        str(Parser(policy=policy.default).parsestr(call.args[2])["Message-ID"])
        for call in transport[0].sendmail.call_args_list
    ]
    assert len(set(ids)) == 3
    assert [report.extra["rfc_message_id"] for report in reports] == ids
    assert [report.message_id for report in reports] == [ids[0], "local-id", ids[2]]


def test_low_level_legacy_positional_call_still_returns_bool_and_generates_id(transport):
    client = SMTPClient(host=CREDS["host"], username=CREDS["username"], password=CREDS["password"])
    success = client.send_email(
        ["recipient@example.test"], "Subject", "text", "", "comenzi@example.test", None, None, None, "Orders"
    )
    assert success is True
    sender, _recipients, mime = submitted(transport)
    assert sender == "comenzi@example.test"
    assert str(mime["From"]) == "Orders <comenzi@example.test>"
    assert mime["Message-ID"]


def test_legacy_false_client_result_still_maps_to_failed(adapter):
    with patch.object(adapter.client, "send_email", return_value=False):
        report = adapter.send(message(message_id="local-id"))
    assert report.status == DeliveryStatus.FAILED
    assert report.message_id == "local-id"
    assert report.error
