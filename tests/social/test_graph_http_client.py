"""
Graph API HTTP errors: the Graph error code decides, not the HTTP status.

A permission error (code 200/10) arrives as HTTP 403 and must not read as a revoked
token; an expired token (code 190) usually arrives as HTTP 400 and must.
"""

from __future__ import annotations

import json

import pytest
import requests

from bapp_connectors.core.errors import (
    AuthenticationError,
    PermanentProviderError,
    ProviderError,
    RateLimitError,
    ValidationError,
)
from bapp_connectors.providers.social.facebook.adapter import FacebookSocialAdapter
from bapp_connectors.providers.social.facebook.http import GraphHttpClient, graph_http_error
from bapp_connectors.providers.social.instagram.adapter import InstagramSocialAdapter
from bapp_connectors.providers.social.meta.adapter import MetaAdapter


def _response(status: int, body) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = (json.dumps(body) if not isinstance(body, str) else body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _graph_error(code: int, message: str, subcode: int | None = None, **extra) -> dict:
    error = {"message": message, "type": "OAuthException", "code": code, **extra}
    if subcode is not None:
        error["error_subcode"] = subcode
    return {"error": error}


def _serve(adapter, status: int, body) -> None:
    adapter.client.http._session.request = lambda *args, **kwargs: _response(status, body)


@pytest.fixture(params=["facebook", "instagram", "meta"])
def adapter(request):
    if request.param == "facebook":
        return FacebookSocialAdapter(credentials={"token": "T", "page_id": "P1"})
    if request.param == "instagram":
        return InstagramSocialAdapter(credentials={"token": "T", "ig_user_id": "IG1"})
    return MetaAdapter(credentials={"token": "T"})


def _call(adapter):
    return adapter.client.get_object("me", "id")


def test_adapters_use_the_graph_client(adapter):
    assert isinstance(adapter.client.http, GraphHttpClient)


def test_403_permission_error_is_not_authentication(adapter):
    _serve(adapter, 403, _graph_error(200, "(#200) The user hasn't authorized the application"))
    with pytest.raises(PermanentProviderError) as exc_info:
        _call(adapter)
    assert not isinstance(exc_info.value, AuthenticationError)
    assert "(#200) The user hasn't authorized the application" in str(exc_info.value)
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == 200


def test_403_code_10_is_not_authentication(adapter):
    _serve(adapter, 403, _graph_error(10, "(#10) Application does not have permission for this action"))
    with pytest.raises(PermanentProviderError, match=r"\(#10\) Application does not have permission"):
        _call(adapter)


def test_400_expired_token_is_authentication(adapter):
    _serve(adapter, 400, _graph_error(190, "Error validating access token: Session has expired", subcode=463))
    with pytest.raises(AuthenticationError, match="Session has expired") as exc_info:
        _call(adapter)
    assert exc_info.value.status_code == 400


def test_400_invalid_parameter_is_validation(adapter):
    _serve(adapter, 400, _graph_error(100, "Invalid parameter"))
    with pytest.raises(ValidationError, match="Invalid parameter"):
        _call(adapter)


def test_400_rate_limit_code_is_rate_limit():
    exc = graph_http_error(_graph_error(4, "Application request limit reached"), 400)
    assert isinstance(exc, RateLimitError)


def test_transient_graph_error_stays_retryable():
    exc = graph_http_error(_graph_error(2, "Service temporarily unavailable", is_transient=True), 400)
    assert type(exc) is ProviderError
    assert exc.retryable


def test_non_graph_4xx_body_keeps_status_classification(adapter):
    _serve(adapter, 401, "<html>Unauthorized</html>")
    with pytest.raises(AuthenticationError):
        _call(adapter)
    _serve(adapter, 404, "not found")
    with pytest.raises(PermanentProviderError):
        _call(adapter)


def test_instagram_keeps_subcode_for_user_not_found():
    adapter = InstagramSocialAdapter(credentials={"token": "T", "ig_user_id": "IG1"})
    _serve(adapter, 400, _graph_error(110, "Invalid user id", subcode=2207013))
    assert adapter.search_mentions("nu_exista") == []
