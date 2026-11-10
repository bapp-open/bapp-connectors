"""Guard on the ``@ai_method`` markers of the messaging provider clients.

A method marked ``read`` is callable by an external AI agent, server-side, with the company's bot
token or page token. The risk of this family is a "get" that consumes: Telegram ``getUpdates``
confirms the queue, Matrix ``/sync`` moves a stored ``since``, SMS gateway inboxes get cleared,
WhatsApp/Messenger "mark as read" are receipts. None of those exist as reads here; the reads are
profiles, guild/room/conversation lists and history fetches that change nothing.

Ids from the agent are checked against the provider's format before they reach a path (Discord
snowflakes, Matrix room ids percent-encoded, Messenger ``t_`` conversations and PSIDs, Telegram chat
ids). Graph ``paging.next/previous`` URLs (they carry ``access_token``) are dropped. Telegram puts
the bot token in the URL, so its reads scrub it from errors; ``getWebhookInfo`` (secret webhook
path) and media/file URL lookups stay unmarked.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest
import requests

from bapp_connectors.core.ai import ai_methods
from bapp_connectors.core.errors import ProviderError, ValidationError
from tests.core import ai_guard

FAMILY = "messaging"
MESSAGING_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "discord": {
        "get_current_user",  # GET users/@me (bot user, no token)
        "list_guilds",  # GET users/@me/guilds
        "get_guild",  # GET guilds/{snowflake}
        "get_guild_channels",  # GET guilds/{snowflake}/channels
        "get_channel",  # GET channels/{snowflake}
        "get_channel_messages",  # GET channels/{snowflake}/messages (history, no ack)
    },
    "goip": {
        "get_send_status",  # GET send_status.xml (queue status, nothing deleted)
    },
    "instagram": {
        "get_account_info",  # GET {ig_user_id}?fields=id,name,username
    },
    "matrix": {
        "whoami",  # GET account/whoami
        "get_joined_rooms",  # GET joined_rooms
        "get_room_messages",  # GET rooms/{encoded id}/messages; joined rooms only; no /sync, no receipt
    },
    "messenger": {
        "get_page_info",  # GET {page_id}?fields=id,name
        "list_conversations",  # GET {page_id}/conversations, fixed fields, paging URLs dropped
        "get_conversation_messages",  # GET {t_...}/messages, fixed fields, paging URLs dropped
        "get_customer_profile",  # GET {psid}?fields=first_name,last_name
    },
    "telegram": {
        "get_bot_info",  # getMe, errors scrubbed of the token
        "get_chat",  # getChat, errors scrubbed of the token
    },
    "whatsapp": {
        "get_phone_number_info",  # GET {phone_number_id}, fixed fields
        "get_business_profile",  # GET {phone_number_id}/whatsapp_business_profile, fixed fields
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

# Opaque pagination cursors: they only reach the query string (params=, encoded by requests).
REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = {
    ("matrix", "get_room_messages", "from_token"),
    ("messenger", "list_conversations", "after"),
    ("messenger", "get_conversation_messages", "after"),
}

# Public client methods deliberately left without any mark (never offered to an agent).
_SEND = "sends or changes messages; not a read"
UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("discord", "test_auth"): "connection test helper",
    ("discord", "send_message"): _SEND + " (dict embeds)",
    ("discord", "send_file"): "multipart upload",
    ("discord", "edit_message"): _SEND,
    ("discord", "delete_message"): _SEND,
    ("discord", "add_reaction"): _SEND,
    ("discord", "respond_to_interaction"): "takes an interaction token",
    ("goip", "test_auth"): "connection test helper",
    ("goip", "send_sms"): "sends; puts the device password in the query",
    ("goip", "clear_received_history"): "deletes the device inbox",
    ("goip", "clear_sent_history"): "deletes the device outbox",
    ("instagram", "test_auth"): "connection test helper",
    ("instagram", "send_attachment"): "Meta fetches an agent URL",
    ("instagram", "send_story_reply"): _SEND,
    ("instagram", "send_reaction"): _SEND,
    ("instagram", "send_generic_template"): _SEND,
    ("instagram", "send_raw"): "raw payload",
    ("matrix", "test_auth"): "connection test helper",
    ("matrix", "send_event"): "any event type to any room",
    ("matrix", "send_image"): _SEND,
    ("matrix", "send_file"): _SEND,
    ("matrix", "send_audio"): _SEND,
    ("matrix", "send_video"): _SEND,
    ("matrix", "send_location"): _SEND,
    ("matrix", "upload_media"): "upload, ../media path",
    ("matrix", "join_room"): "joins a room (membership change)",
    ("messenger", "test_auth"): "connection test helper",
    ("messenger", "get_user_profile"): "agent-chosen node and fields (a Page's access_token)",
    ("messenger", "send_attachment"): "Meta fetches an agent URL",
    ("messenger", "send_attachment_by_id"): _SEND,
    ("messenger", "send_generic_template"): _SEND,
    ("messenger", "send_button_template"): _SEND,
    ("messenger", "send_quick_replies"): _SEND,
    ("messenger", "send_action"): "mark_seen / typing indicators",
    ("messenger", "send_raw"): "raw payload",
    ("robosms", "test_auth"): "sends a dummy SMS",
    ("telegram", "test_auth"): "connection test helper",
    ("telegram", "get_me"): "errors may quote the URL with the bot token; the agent uses get_bot_info",
    ("telegram", "get_webhook_info"): "webhook URL usually carries a secret path",
    ("telegram", "set_webhook"): "changes the webhook",
    ("telegram", "delete_webhook"): "changes the webhook / drops pending updates",
    ("telegram", "send_message"): _SEND,
    ("telegram", "send_photo"): _SEND,
    ("telegram", "send_document"): _SEND,
    ("telegram", "send_video"): _SEND,
    ("telegram", "send_audio"): _SEND,
    ("telegram", "send_voice"): _SEND,
    ("telegram", "send_sticker"): _SEND,
    ("telegram", "send_animation"): _SEND,
    ("telegram", "send_location"): _SEND,
    ("telegram", "send_contact"): _SEND,
    ("telegram", "edit_message_text"): _SEND,
    ("telegram", "delete_message"): _SEND,
    ("telegram", "forward_message"): _SEND,
    ("whatsapp", "test_auth"): "connection test helper",
    ("whatsapp", "get_media_url"): "any Graph node; returns a media download URL",
    ("whatsapp", "delete_media"): "deletes",
    ("whatsapp", "mark_as_read"): "read receipt",
    ("whatsapp", "send_template"): _SEND,
    ("whatsapp", "send_image"): "Meta fetches an agent URL",
    ("whatsapp", "send_document"): "Meta fetches an agent URL",
    ("whatsapp", "send_video"): "Meta fetches an agent URL",
    ("whatsapp", "send_audio"): "Meta fetches an agent URL",
    ("whatsapp", "send_sticker"): "Meta fetches an agent URL",
    ("whatsapp", "send_location"): _SEND,
    ("whatsapp", "send_interactive"): _SEND,
    ("whatsapp", "send_contacts"): _SEND,
    ("whatsapp", "send_reaction"): _SEND,
    ("whatsapp", "send_raw"): "raw payload",
}

NOT_MARKED: dict[str, str] = {
    "robosms": "the API only sends SMS (send_sms is a write label); there is no read endpoint in the client",
}


def test_every_messaging_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in MESSAGING_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_messaging_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", MESSAGING_PROVIDERS)
def test_every_public_method_is_marked_or_left_out_on_purpose(provider):
    """A new public client method fails here until it is marked or listed as unmarked."""
    cls = ai_guard.client_cls(FAMILY, provider)
    marked = set(ai_methods(cls))
    public = {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_") and callable(value) and not isinstance(value, (staticmethod, classmethod))
    }
    assert public - marked == {m for p, m in UNMARKED_ON_PURPOSE if p == provider}


@pytest.mark.parametrize("provider", _CHECKED)
def test_no_read_takes_a_host_url_path_fields_or_token(provider):
    blocked = {"url", "host", "base_url", "version", "api_version", "path", "fields", "access_token", "token", "offset"}
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        assert not set(inspect.signature(fn).parameters) & blocked, name


CONSUMING = {"getUpdates", "sync", "receipt", "read_markers", "mark_as_read", "mark_seen", "del", "clear"}


@pytest.mark.parametrize("provider", _CHECKED)
def test_reads_are_not_consuming_calls(provider):
    """No read's source mentions a consuming endpoint (update queue, sync, receipts, inbox delete)."""
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        source = inspect.getsource(fn)
        for word in CONSUMING:
            assert f'"{word}' not in source and f"/{word}" not in source, (name, word)


# ── Discord: snowflakes only ──


def _discord(response=None):
    from bapp_connectors.providers.messaging.discord.client import DiscordApiClient

    http = MagicMock()
    http.call.return_value = response if response is not None else []
    return DiscordApiClient(http), http


def test_discord_reads_hit_fixed_paths():
    client, http = _discord()
    client.get_current_user()
    client.list_guilds()
    client.get_guild("123")
    client.get_guild_channels("123")
    client.get_channel("456")
    client.get_channel_messages("456", limit=500, before="789")
    assert [c.args for c in http.call.call_args_list] == [
        ("GET", "users/@me"),
        ("GET", "users/@me/guilds"),
        ("GET", "guilds/123"),
        ("GET", "guilds/123/channels"),
        ("GET", "channels/456"),
        ("GET", "channels/456/messages"),
    ]
    assert http.call.call_args.kwargs["params"] == {"limit": 100, "before": "789"}


@pytest.mark.parametrize("bad", ["@me", "123/messages", "12%2F3", "", "abc", "1 2", "١٢٣", "1" * 21])
def test_discord_refuses_non_snowflakes(bad):
    client, http = _discord()
    for call in (
        lambda: client.get_guild(bad),
        lambda: client.get_guild_channels(bad),
        lambda: client.get_channel(bad),
        lambda: client.get_channel_messages(bad),
        lambda: client.get_channel_messages("1", before=bad or "x"),
        lambda: client.get_channel_messages("1", after=bad or "x"),
    ):
        with pytest.raises(ValidationError):
            call()
    http.call.assert_not_called()


# ── Matrix: room ids encoded, joined rooms only, no /sync ──


def _matrix(joined=("!abc:example.org",)):
    from bapp_connectors.providers.messaging.matrix.client import MatrixApiClient

    http = MagicMock()

    def call(method, path, **kwargs):
        if path == "joined_rooms":
            return {"joined_rooms": list(joined)}
        return {"chunk": [], "start": "s1", "end": "s2"}

    http.call.side_effect = call
    return MatrixApiClient(http), http


def test_matrix_room_messages_encode_the_room_id():
    client, http = _matrix()
    client.get_room_messages("!abc:example.org", limit=10, from_token="t1-2_3&x=1")
    method, path = http.call.call_args.args
    assert (method, path) == ("GET", "rooms/%21abc%3Aexample.org/messages")
    assert http.call.call_args.kwargs["params"] == {"dir": "b", "limit": 10, "from": "t1-2_3&x=1"}


def test_matrix_room_id_cannot_leave_the_homeserver():
    from bapp_connectors.core.http import ResilientHttpClient

    client, http = _matrix(joined=("!abc:evil.example:8448",))
    client.get_room_messages("!abc:evil.example:8448")
    path = http.call.call_args.args[1]
    url = ResilientHttpClient(base_url="https://matrix.example.org/_matrix/client/v3/")._build_url(path)
    assert url.startswith("https://matrix.example.org/_matrix/client/v3/rooms/%21abc%3Aevil.example%3A8448/")


def test_matrix_refuses_a_room_not_joined():
    client, http = _matrix(joined=("!other:example.org",))
    with pytest.raises(ValidationError):
        client.get_room_messages("!abc:example.org")
    assert [c.args[1] for c in http.call.call_args_list] == ["joined_rooms"]


@pytest.mark.parametrize(
    "bad", ["abc:example.org", "#alias:example.org", "!a/b:example.org", "!a:ex/ample", "!a..b:x", "!a:x?y", "", "!"]
)
def test_matrix_refuses_bad_room_ids(bad):
    client, http = _matrix(joined=(bad,))
    with pytest.raises(ValidationError):
        client.get_room_messages(bad)
    http.call.assert_not_called()


def test_matrix_room_v12_ids_without_server_are_accepted():
    client, http = _matrix(joined=("!31hneApxJ_1o-63DmFrpeqnkFfWppnzWso1JvH3ogLM",))
    client.get_room_messages("!31hneApxJ_1o-63DmFrpeqnkFfWppnzWso1JvH3ogLM")
    assert http.call.call_args.args[1].startswith("rooms/%2131hneApxJ_1o-63DmFrpeqnkFfWppnzWso1JvH3ogLM/")


# ── Messenger: fixed fields, Page conversations, paging URLs dropped ──


def _messenger(response=None):
    from bapp_connectors.providers.messaging.messenger.client import MessengerApiClient

    http = MagicMock()
    http.call.return_value = (
        response
        if response is not None
        else {
            "data": [],
            "paging": {
                "cursors": {"after": "A"},
                "next": "https://graph.facebook.com/v21.0/1/conversations?access_token=SECRET",
                "previous": "https://graph.facebook.com/v21.0/1/conversations?access_token=SECRET",
            },
        }
    )
    return MessengerApiClient(http, page_id="111"), http


def test_messenger_reads_use_fixed_fields_and_drop_paging_urls():
    client, http = _messenger()
    out1 = client.list_conversations(limit=5, after="A")
    out2 = client.get_conversation_messages("t_123", after="B")
    client.get_customer_profile("42")
    client.get_page_info()
    for out in (out1, out2):
        assert out["paging"] == {"cursors": {"after": "A"}}
    calls = http.call.call_args_list
    assert [c.args for c in calls] == [
        ("GET", "111/conversations"),
        ("GET", "t_123/messages"),
        ("GET", "42"),
        ("GET", "111"),
    ]
    for c in calls:
        assert "access_token" not in c.kwargs["params"]["fields"]
    assert calls[0].kwargs["params"]["after"] == "A"


@pytest.mark.parametrize("bad", ["111", "t_1/messages", "t_1..x", "me", "", "t_", "t_a%2Fb"])
def test_messenger_refuses_non_conversation_ids(bad):
    client, http = _messenger()
    with pytest.raises(ValidationError):
        client.get_conversation_messages(bad)
    http.call.assert_not_called()


@pytest.mark.parametrize("bad", ["me", "111?fields=access_token", "", "1/2", "١٢"])
def test_messenger_refuses_non_numeric_psid(bad):
    client, http = _messenger()
    with pytest.raises(ValidationError):
        client.get_customer_profile(bad)
    http.call.assert_not_called()


# ── WhatsApp: fixed fields on the connected number ──


def test_whatsapp_reads_stay_on_the_connected_number():
    from bapp_connectors.providers.messaging.whatsapp.client import WhatsAppApiClient

    http = MagicMock()
    http.call.return_value = {}
    client = WhatsAppApiClient(http, phone_number_id="555")
    client.get_phone_number_info()
    client.get_business_profile()
    calls = http.call.call_args_list
    assert [c.args for c in calls] == [("GET", "555"), ("GET", "555/whatsapp_business_profile")]
    for c in calls:
        assert "token" not in c.kwargs["params"]["fields"]


# ── Telegram: getChat / getMe only, chat ids checked, the token never in an error ──


def _telegram(side_effect=None):
    from bapp_connectors.providers.messaging.telegram.client import TelegramApiClient

    http = MagicMock()
    http.base_url = "https://api.telegram.org/bot123456:AA-secret_Tok/"
    if side_effect is not None:
        http.call.side_effect = side_effect
    else:
        http.call.return_value = {"ok": True, "result": {"id": 1}}
    return TelegramApiClient(http), http


def test_telegram_reads_call_get_me_and_get_chat_only():
    client, http = _telegram()
    assert client.get_bot_info() == {"id": 1}
    client.get_chat("-1001234567890")
    client.get_chat("@some_channel")
    assert [c.args for c in http.call.call_args_list] == [("POST", "getMe"), ("POST", "getChat"), ("POST", "getChat")]
    assert http.call.call_args.kwargs["json"] == {"chat_id": "@some_channel"}


@pytest.mark.parametrize("bad", ["", "abc", "@ab", "@x/y", "1.5", "-", "@" + "a" * 40, "1 2"])
def test_telegram_refuses_bad_chat_ids(bad):
    client, http = _telegram()
    with pytest.raises(ValidationError):
        client.get_chat(bad)
    http.call.assert_not_called()


@pytest.mark.parametrize("call", ["get_bot_info", "get_chat"])
def test_telegram_errors_never_carry_the_bot_token(call):
    err = requests.ConnectionError(
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded with url: "
        "/bot123456:AA-secret_Tok/getMe and /bot123456%3AAA-secret_Tok/getChat"
    )
    client, _http = _telegram(side_effect=err)
    with pytest.raises(ProviderError) as info:
        getattr(client, call)(*(["42"] if call == "get_chat" else []))
    text = str(info.value)
    assert "secret_Tok" not in text and "123456:AA" not in text
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_telegram_update_queue_is_not_reachable():
    from bapp_connectors.providers.messaging.telegram.client import TelegramApiClient

    assert not hasattr(TelegramApiClient, "get_updates")
    assert "get_webhook_info" not in ai_methods(TelegramApiClient)
