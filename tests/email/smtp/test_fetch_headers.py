"""Synthetic imaplib FETCH responses: tuples are literals, not messages."""

from unittest.mock import MagicMock

import pytest

from bapp_connectors.providers.email.smtp.adapter import SMTPEmailAdapter
from bapp_connectors.providers.email.smtp.client import IMAPClient

HEADERS = (
    b"Subject: Synthetic delivery report\r\n"
    b"From: sender@example.test\r\n"
    b"To: recipient@example.test\r\n"
    b"X-Folded: first\r\n second\r\n\r\n"
)
PLAIN = b'("text" "plain" NIL NIL NIL "7bit" 10 1)'


def _literal(metadata, value):
    return metadata + b"{" + str(len(value)).encode() + b"}", value


def _ordinary(sequence=1, uid=101):
    return [
        _literal(f"{sequence} (UID {uid} FLAGS (\\Seen) BODY[HEADER] ".encode(), HEADERS),
        b" BODYSTRUCTURE " + PLAIN + b")",
    ]


def _delivery_report(*, uid_in_trailer=False, literal_disposition=False):
    # Each description is an IMAP string literal inside BODYSTRUCTURE. imaplib
    # returns it in a separate tuple, even though it belongs to the same FETCH.
    prefix = b"7 (" if uid_in_trailer else b"7 (UID 107 FLAGS (\\Seen \\Flagged) "
    parts = [
        _literal(prefix + b"BODY[HEADER] ", HEADERS),
        _literal(
            b' BODYSTRUCTURE (("text" "plain" ("charset" "utf-8") NIL ',
            b'Synthetic description (with parentheses), "quotes" and UID 999',
        ),
        _literal(
            b' "7bit" 10 1 NIL NIL NIL)("message" "delivery-status" NIL NIL ',
            b"Synthetic status description",
        ),
    ]
    if literal_disposition:
        parts.append(_literal(b' "7bit" 20 NIL (', b"attachment"))
        tail = b' ("filename" "status.txt")) NIL)'
    else:
        tail = b' "7bit" 20 NIL ("attachment" ("filename" "status.txt")) NIL)'
    tail += b' "report" ("report-type" "delivery-status") NIL NIL)'
    if uid_in_trailer:
        tail += b" UID 107 FLAGS (\\Seen \\Flagged)"
    return [*parts, tail + b")"]


def _client(data, *, status="OK"):
    client = IMAPClient(host="imap.example.test")
    connection = MagicMock()
    connection.select.return_value = ("OK", [b"1"])
    connection.uid.return_value = (status, data)
    client._connect = MagicMock(return_value=connection)
    return client, connection


def test_ordinary_fetch_preserves_headers_flags_and_command():
    client, connection = _client(_ordinary())

    results = client.fetch_headers(["101"])

    assert len(results) == 1
    uid, message, flags, attached = results[0]
    assert uid == "101"
    assert message["Subject"] == "Synthetic delivery report"
    assert message["From"] == "sender@example.test"
    assert message["To"] == "recipient@example.test"
    assert message["X-Folded"] == "first\r\n second"
    assert flags == {"\\Seen"}
    assert attached is False
    connection.uid.assert_called_once_with("fetch", "101", "(FLAGS BODY[HEADER] BODYSTRUCTURE)")
    connection.logout.assert_called_once()


def test_uid_and_flags_in_continuation_after_header_literal():
    client, _ = _client(
        [
            _literal(b"2 (BODY[HEADER] ", HEADERS),
            b" BODYSTRUCTURE " + PLAIN + b" UID 102 FLAGS (\\Flagged))",
        ]
    )

    results = client.fetch_headers(["102"])

    assert len(results) == 1
    assert results[0][0] == "102"
    assert results[0][2] == {"\\Flagged"}
    assert results[0][3] is False


@pytest.mark.parametrize("uid_in_trailer", [False, True])
@pytest.mark.parametrize("literal_disposition", [False, True])
def test_delivery_report_literals_belong_to_one_message(uid_in_trailer, literal_disposition):
    client, _ = _client(
        _delivery_report(
            uid_in_trailer=uid_in_trailer,
            literal_disposition=literal_disposition,
        )
    )

    results = client.fetch_headers(["107"])

    assert len(results) == 1
    uid, message, flags, attached = results[0]
    assert uid == "107"
    assert message["Subject"] == "Synthetic delivery report"
    assert flags == {"\\Seen", "\\Flagged"}
    assert attached is True


def test_bodystructure_literals_before_headers_and_uid():
    client, _ = _client(
        [
            _literal(b'3 (BODYSTRUCTURE ("text" "plain" NIL NIL ', b"description"),
            _literal(b' "7bit" 10 1) UID 103 BODY[HEADER] ', HEADERS),
            b" FLAGS ())",
        ]
    )

    results = client.fetch_headers(["103"])

    assert len(results) == 1
    assert results[0][0] == "103"
    assert results[0][1]["Subject"] == "Synthetic delivery report"
    assert results[0][2:] == (set(), False)


def test_uid_and_flags_in_metadata_of_a_later_literal():
    client, _ = _client(
        [
            _literal(b"3 (BODY[HEADER] ", HEADERS),
            _literal(b' UID 103 FLAGS (\\Seen) BODYSTRUCTURE ("text" "plain" NIL NIL ', b"description"),
            b' "7bit" 10 1))',
        ]
    )

    results = client.fetch_headers(["103"])

    assert len(results) == 1
    assert results[0][0] == "103"
    assert results[0][2] == {"\\Seen"}
    assert results[0][3] is False


def test_quoted_metadata_cannot_supply_uid_flags_or_response_boundaries():
    client, _ = _client(
        [
            _literal(b"3 (BODY[HEADER] ", HEADERS),
            b' BODYSTRUCTURE ("text" "plain" NIL NIL "escaped \\"quote\\" (UID 999 FLAGS (\\\\Seen))"'
            b' "7bit" 10 1) uid 103 flags (\\Flagged))',
        ]
    )

    results = client.fetch_headers(["103"])

    assert len(results) == 1
    assert results[0][0] == "103"
    assert results[0][2:] == ({"\\Flagged"}, False)


def test_literal_header_bytes_are_not_imap_metadata():
    headers = HEADERS.replace(b"Subject: Synthetic delivery report", b'Subject: ) UID 999 ("attachment")')
    client, _ = _client(
        [
            _literal(b"1 (BODY[HEADER] ", headers),
            b" UID 101 FLAGS () BODYSTRUCTURE " + PLAIN + b")",
        ]
    )

    results = client.fetch_headers(["101"])

    assert len(results) == 1
    assert results[0][0] == "101"
    assert results[0][1]["Subject"] == ') UID 999 ("attachment")'
    assert results[0][2:] == (set(), False)


def test_multiple_messages_and_repeated_fetch_have_no_phantoms_or_duplicates():
    data = [*_ordinary(), *_delivery_report(uid_in_trailer=True), *_ordinary(8, 108), *_ordinary(8, 108)]
    client, _ = _client(data)
    adapter = SMTPEmailAdapter(credentials={"host": "smtp.example.test"})
    adapter.imap_client = client
    client.fetch_uids = MagicMock(return_value=["101", "107", "108"])

    summaries = adapter.fetch_messages()

    assert [summary.message_id for summary in summaries] == ["101", "107", "108"]
    assert [summary.has_attachments for summary in summaries] == [False, True, False]
    assert all(summary.subject == "Synthetic delivery report" for summary in summaries)
    assert summaries[1].is_read and summaries[1].is_flagged


@pytest.mark.parametrize(
    "invalid",
    [
        [_literal(b"2 (BODY[HEADER] ", HEADERS), b" FLAGS ())"],  # missing UID
        [_literal(b"2 (UID 0 BODY[HEADER] ", HEADERS), b")"],
        [_literal(b"2 (UID bad BODY[HEADER] ", HEADERS), b")"],
        [_literal(b"2 (UID 4294967296 BODY[HEADER] ", HEADERS), b")"],
        [_literal(b'2 (UID "102" BODY[HEADER] ', HEADERS), b")"],
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS), b" UID 103)"],
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS), b" FLAGS NIL)"],
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS)],  # missing closing parenthesis
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS), b"))"],
        [(b"2 (UID 102 BODY[HEADER] {9999}", HEADERS), b")"],
        [b"2 (UID 102 FLAGS ())"],  # unsolicited flags, no headers
        [b"2 (UID 102 BODY[HEADER] NIL)"],
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS), b' BODYSTRUCTURE ("unterminated))'],
        [_literal(b"2 (UID 102 BODY[HEADER] ", HEADERS), None],
        [(b"2 (UID 102 BODY[HEADER] {1}",)],
        [b"2 (UID 102 BODY[HEADER]"],
        [_literal(b"2 (BODY[HEADER] ", HEADERS), b' BODYSTRUCTURE ("UID 999"))'],
    ],
)
def test_invalid_or_incomplete_response_does_not_lose_valid_neighbours(invalid):
    client, _ = _client([*_ordinary(), *invalid, *_ordinary(3, 103)])

    results = client.fetch_headers(["101", "102", "103"])

    assert [item[0] for item in results] == ["101", "103"]


def test_orphan_bodystructure_fragments_are_not_messages():
    client, _ = _client(
        [
            None,
            _literal(b' BODYSTRUCTURE (("text" "plain" NIL NIL ', b"description"),
            b' "7bit" 10 1) "mixed"))',
            *_ordinary(),
        ]
    )

    assert [item[0] for item in client.fetch_headers(["101"])] == ["101"]


def test_orphan_fragments_after_a_complete_message_do_not_discard_it():
    client, _ = _client([*_ordinary(), None, (b" BODYSTRUCTURE {4}", b"test"), b"))", *_ordinary(2, 102)])

    assert [item[0] for item in client.fetch_headers(["101", "102"])] == ["101", "102"]


def test_empty_header_literal_and_zero_padded_length_are_valid():
    client, _ = _client([(b"1 (UID 101 BODY[HEADER] {00}", b""), b" FLAGS ())"])

    results = client.fetch_headers(["101"])

    assert len(results) == 1
    assert results[0][0] == "101"
    assert list(results[0][1].items()) == []


def test_invalid_response_logs_do_not_include_server_data(caplog):
    client, _ = _client([_literal(b"1 (BODY[HEADER] ", HEADERS), b")"])

    assert client.fetch_headers(["101"]) == []
    assert "Skipping" in caplog.text
    assert "Synthetic" not in caplog.text
    assert "sender@example.test" not in caplog.text


@pytest.mark.parametrize("data", [None, [], [None], [b""]])
def test_empty_fetch(data):
    client, connection = _client(data)
    assert client.fetch_headers(["101"]) == []
    connection.logout.assert_called_once()


def test_failed_fetch_and_empty_uid_list():
    client, connection = _client(_ordinary(), status="NO")
    assert client.fetch_headers(["101"]) == []
    connection.logout.assert_called_once()
    client._connect.reset_mock()
    assert client.fetch_headers([]) == []
    client._connect.assert_not_called()
