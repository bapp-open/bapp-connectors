"""
Authentication strategies for the HTTP client.

Each strategy applies auth to a requests.PreparedRequest or provides auth kwargs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from requests.auth import HTTPBasicAuth


class BaseAuthStrategy(ABC):
    """Base class for authentication strategies."""

    @abstractmethod
    def apply_to_headers(self, headers: dict) -> dict:
        """Apply auth to request headers. Returns updated headers dict."""
        ...

    def get_auth(self) -> HTTPBasicAuth | None:
        """Return a requests auth object if applicable."""
        return None


class NoAuth(BaseAuthStrategy):
    """No authentication."""

    def apply_to_headers(self, headers: dict) -> dict:
        return headers


class BasicAuth(BaseAuthStrategy):
    """HTTP Basic Authentication."""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def apply_to_headers(self, headers: dict) -> dict:
        return headers

    def get_auth(self) -> HTTPBasicAuth:
        return HTTPBasicAuth(self.username, self.password)


class TokenAuth(BaseAuthStrategy):
    """Token-based auth (Authorization header with configurable prefix)."""

    def __init__(self, token: str, prefix: str = "", header: str = "Authorization"):
        self.token = token
        self.prefix = prefix
        self.header = header

    def apply_to_headers(self, headers: dict) -> dict:
        if self.prefix:
            headers[self.header] = f"{self.prefix} {self.token}"
        else:
            headers[self.header] = self.token
        return headers


class BearerAuth(TokenAuth):
    """Bearer token auth (shorthand for TokenAuth with 'Bearer' prefix)."""

    def __init__(self, token: str):
        super().__init__(token, prefix="Bearer")


class ApiKeyAuth(BaseAuthStrategy):
    """API key sent in a custom header."""

    def __init__(self, key: str, header: str = "X-API-Key"):
        self.key = key
        self.header = header

    def apply_to_headers(self, headers: dict) -> dict:
        headers[self.header] = self.key
        return headers


class MultiHeaderAuth(BaseAuthStrategy):
    """Multiple custom headers (e.g., Gomag uses ApiShop + Apikey)."""

    def __init__(self, headers: dict[str, str]):
        self._headers = headers

    def apply_to_headers(self, headers: dict) -> dict:
        headers.update(self._headers)
        return headers
