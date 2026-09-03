import pytest

from bapp_connectors.core.errors import AuthenticationError, PermanentProviderError, ProviderError
from bapp_connectors.providers.shop.bapp_store.errors import map_error, raise_for_status
from tests.shop.bapp_store.fake_response import FakeResponse


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses_map_to_authentication_error(status):
    err = map_error(status, '{"detail": "bad token"}')
    assert isinstance(err, AuthenticationError)
    assert err.retryable is False
    assert err.status_code == status
    assert "bad token" in str(err)


@pytest.mark.parametrize("status", [400, 404, 413])
def test_other_4xx_is_permanent(status):
    err = map_error(status, "too large")
    assert isinstance(err, PermanentProviderError)
    assert err.retryable is False and err.status_code == status


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_is_retryable(status):
    err = map_error(status, "boom")
    assert isinstance(err, ProviderError)
    assert err.retryable is True and err.status_code == status


def test_body_is_truncated():
    assert len(str(map_error(500, "x" * 2000))) < 600


def test_raise_for_status_passes_2xx_and_raises_errors():
    raise_for_status(FakeResponse(status_code=200, payload={}))
    with pytest.raises(PermanentProviderError):
        raise_for_status(FakeResponse(status_code=413, text="over 100 products"))
