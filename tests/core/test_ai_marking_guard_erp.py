"""Guard on the ``@ai_method`` markers of the ERP provider clients.

BAPP ERP talks to another BAPP company's API with that company's token. ``run_task`` runs any
task code and stays unmarked; so do printing and SMS. The only read is ``get_capabilities``, a
fixed task (``company_device.BappCapabilities``) that lists print devices, printers and SMS
phones: ids, aliases and printer names, no tokens.
"""

from __future__ import annotations

import inspect
import json

import pytest

from bapp_connectors.core.ai import ai_methods
from tests.core import ai_guard
from tests.fake_http import FakeHttpClient

FAMILY = "erp"
ERP_PROVIDERS = ai_guard.family_providers(FAMILY)

REVIEWED_READ_METHODS: dict[str, set[str]] = {
    "bapp": {
        "get_capabilities",  # POST tasks/company_device.BappCapabilities, no options
    },
}

REVIEWED_READ_EXTRA: dict[tuple[str, str], dict[str, str]] = {}

REVIEWED_FREE_TEXT: set[tuple[str, str, str]] = set()

UNMARKED_ON_PURPOSE: dict[tuple[str, str], str] = {
    ("bapp", "run_task"): "runs any task code of the remote BAPP",
    ("bapp", "print_file"): "prints; takes a URL",
    ("bapp", "send_sms"): "sends an SMS",
}

NOT_MARKED: dict[str, str] = {}


def test_every_erp_provider_is_reviewed_or_not_marked():
    ai_guard.check_family_coverage(FAMILY, REVIEWED_READ_METHODS, NOT_MARKED)


_CHECKED = [p for p in ERP_PROVIDERS if p not in NOT_MARKED]


@pytest.mark.parametrize("check", ai_guard.GENERIC_CHECKS, ids=lambda c: c.__name__)
@pytest.mark.parametrize("provider", _CHECKED)
def test_erp_marks(provider, check):
    kwargs = {"free_text": REVIEWED_FREE_TEXT} if check is ai_guard.check_free_text_reviewed else {}
    check(FAMILY, provider, REVIEWED_READ_METHODS, REVIEWED_READ_EXTRA, **kwargs)


@pytest.mark.parametrize("provider", _CHECKED)
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
def test_no_read_takes_a_task_code_or_host(provider):
    for name, fn, _info in ai_guard.read_methods(FAMILY, provider):
        params = set(inspect.signature(fn).parameters) - {"self"}
        assert not params, f"{name} takes {params}"


class _Response:
    status_code = 200

    def __init__(self, body):
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_bapp_capabilities_posts_the_fixed_task_once():
    from bapp_connectors.providers.erp.bapp.client import TASK_CAPABILITIES, BappErpApiClient

    http = FakeHttpClient()
    data = {"print": True, "sms": False, "devices": [{"id": "d1", "alias": "Birou", "printers": ["HP"]}], "phones": []}
    http.add("POST", "tasks/", _Response({"finished": True, "failed": False, "message": "", "data": data}))
    client = BappErpApiClient(http, token="T1", base_url="https://panel.bapp.ro/api/")
    assert client.get_capabilities() == data
    assert [(c.method, c.path) for c in http.calls] == [
        ("POST", f"https://panel.bapp.ro/api/tasks/{TASK_CAPABILITIES}")
    ]
    assert http.calls[0].kwargs["json"] == {}


def test_bapp_no_ai_client_when_the_url_may_not_carry_the_token():
    from bapp_connectors.core.registry import registry

    good = ai_guard.adapter(FAMILY, "bapp")
    assert good.get_ai_client() is good.client
    with ai_guard.no_network():
        bad = registry.create_adapter(
            FAMILY, "bapp", credentials={"token": "x"}, config={"base_url": "https://evil.example.com/api/"}
        )
    assert bad.get_ai_client() is None
