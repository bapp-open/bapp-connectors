"""
A server whose only host key algorithm is ``ssh-rsa`` — no server, no Docker, always run.

Paramiko 5 dropped ``ssh-rsa`` (RSA signed with SHA-1) altogether, so a server that
offers nothing else — an old Cerberus, an appliance nobody upgrades — ends the
handshake with "Incompatible ssh peer (no acceptable host key)". `SFTPClient` can be
told to accept that signature again, for the host key only and only as a last resort.
"""

from __future__ import annotations

import socket
from unittest import mock

import pytest

paramiko = pytest.importorskip(
    "paramiko", reason="SFTP needs the [sftp] extra", exc_type=ImportError
)

from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

from bapp_connectors.providers.storage.sftp.adapter import SFTPStorageAdapter  # noqa: E402
from bapp_connectors.providers.storage.sftp.client import SFTPClient  # noqa: E402
from bapp_connectors.providers.storage.sftp.manifest import manifest  # noqa: E402

needs_paramiko_5 = pytest.mark.skipif(
    "ssh-rsa" in paramiko.Transport._preferred_keys,
    reason="this paramiko still negotiates ssh-rsa on its own",
)

EXCHANGE_HASH = b"H" * 32


@pytest.fixture(scope="module")
def sha1_signed_host():
    """A real RSA host key and what an ``ssh-rsa`` server sends to prove it owns it."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    signature = paramiko.Message()
    signature.add_string("ssh-rsa")
    signature.add_string(private.sign(EXCHANGE_HASH, padding.PKCS1v15(), hashes.SHA1()))
    return paramiko.RSAKey(key=private).asbytes(), signature.asbytes()


def verifies(transport_class, host) -> bool:
    """What ``Transport._verify_key`` does with the host key it was sent."""
    blob, signature = host
    key = transport_class._key_info["ssh-rsa"](paramiko.Message(blob))
    return key.verify_ssh_sig(EXCHANGE_HASH, paramiko.Message(signature))


def client(**kwargs) -> SFTPClient:
    return SFTPClient(host="gazda.test", username="u", password="p", **kwargs)


def test_left_alone_the_client_negotiates_exactly_what_paramiko_does():
    assert client()._transport_class() is paramiko.Transport


@needs_paramiko_5
def test_asked_to_it_offers_ssh_rsa_after_everything_paramiko_prefers():
    """Last in the list: the algorithm is the first of ours the server also has, so a
    server with anything better never gets as far as ``ssh-rsa``."""
    legacy = client(allow_legacy_host_key=True)._transport_class()

    assert issubclass(legacy, paramiko.Transport)
    assert tuple(legacy._preferred_keys) == (*paramiko.Transport._preferred_keys, "ssh-rsa")


@needs_paramiko_5
def test_asked_to_it_accepts_a_host_key_signed_with_sha1(sha1_signed_host):
    legacy = client(allow_legacy_host_key=True)._transport_class()

    assert verifies(legacy, sha1_signed_host)


@needs_paramiko_5
def test_a_signature_that_does_not_match_is_still_refused(sha1_signed_host):
    """Accepting the algorithm is not accepting anything signed with it."""
    blob, _signature = sha1_signed_host
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = paramiko.Message()
    forged.add_string("ssh-rsa")
    forged.add_string(other.sign(EXCHANGE_HASH, padding.PKCS1v15(), hashes.SHA1()))
    legacy = client(allow_legacy_host_key=True)._transport_class()

    assert not verifies(legacy, (blob, forged.asbytes()))


@needs_paramiko_5
def test_only_the_host_key_is_relaxed_never_what_we_sign_with():
    """Our own public-key authentication keeps to SHA-2: the server's choice of host
    key says nothing about what we are willing to sign."""
    legacy = client(allow_legacy_host_key=True)._transport_class()

    assert tuple(legacy._preferred_pubkeys) == tuple(paramiko.Transport._preferred_pubkeys)
    assert "ssh-rsa" not in legacy._preferred_pubkeys
    assert "ssh-rsa" not in paramiko.RSAKey.HASHES


@needs_paramiko_5
def test_paramiko_itself_is_left_as_it_was():
    """A subclass, not a patch: every other connection in the process — and every
    client that did not ask — negotiates as before."""
    client(allow_legacy_host_key=True)._transport_class()

    assert "ssh-rsa" not in paramiko.Transport._preferred_keys
    assert "ssh-rsa" not in paramiko.Transport._key_info
    assert client()._transport_class() is paramiko.Transport


def test_the_connection_is_built_from_that_transport():
    legacy = client(allow_legacy_host_key=True)
    build = mock.Mock(name="LegacyTransport")
    legacy._transport_class = lambda: build  # type: ignore[method-assign]

    with mock.patch.object(socket, "create_connection") as create:
        assert legacy._connect_transport() is build.return_value

    build.assert_called_once_with(create.return_value)
    build.return_value.connect.assert_called_once_with(username="u", password="p", pkey=None)


# ── how a caller reaches it ──

def test_it_is_off_unless_the_connection_says_otherwise():
    adapter = SFTPStorageAdapter(credentials={"host": "gazda.test", "username": "u", "password": "p"})

    assert adapter.client.allow_legacy_host_key is False


def test_the_connection_setting_reaches_the_client():
    adapter = SFTPStorageAdapter(
        credentials={"host": "gazda.test", "username": "u", "password": "p"},
        config={"allow_legacy_host_key": True},
    )

    assert adapter.client.allow_legacy_host_key is True


def test_the_manifest_offers_it_switched_off():
    field = next(f for f in manifest.settings.fields if f.name == "allow_legacy_host_key")

    assert field.default is False
