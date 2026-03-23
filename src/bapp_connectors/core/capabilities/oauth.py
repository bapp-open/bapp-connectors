"""
OAuth capability — optional interface for providers using OAuth2 flow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class OAuthTokens:
    """OAuth2 token pair."""

    access_token: str
    refresh_token: str = ""
    expires_in: int | None = None
    token_type: str = "Bearer"
    extra: dict | None = None


class OAuthCapability(ABC):
    """Adapter supports OAuth2 authentication flow."""

    @abstractmethod
    def get_authorize_url(self, redirect_uri: str, state: str = "") -> str:
        """Generate the OAuth2 authorization URL the user should be redirected to."""
        ...

    @abstractmethod
    def exchange_code_for_token(self, code: str, redirect_uri: str, state: str = "") -> OAuthTokens:
        """Exchange an authorization code for access/refresh tokens."""
        ...

    @abstractmethod
    def refresh_token(self, refresh_token: str) -> OAuthTokens:
        """Refresh an expired access token using the refresh token."""
        ...
