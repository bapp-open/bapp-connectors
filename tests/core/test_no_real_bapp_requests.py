"""The autouse guard in tests/conftest.py refuses real HTTP requests to bapp.ro hosts."""

import pytest
import requests
import responses


def test_real_request_to_panel_is_refused():
    with pytest.raises(RuntimeError, match="panel.bapp.ro"):
        requests.post("https://panel.bapp.ro/api/tasks/company_device.BappCapabilities", json={})


def test_subdomain_store_is_refused_too():
    with pytest.raises(RuntimeError, match="demo.sites.bapp.ro"):
        requests.get("https://demo.sites.bapp.ro/")


@responses.activate
def test_responses_mock_still_answers():
    responses.add(responses.POST, "https://panel.bapp.ro/api/tasks/x", json={"ok": True})
    assert requests.post("https://panel.bapp.ro/api/tasks/x").json() == {"ok": True}
