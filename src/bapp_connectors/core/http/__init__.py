"""Resilient HTTP client with auth, retry, rate limiting, and middleware."""

from .auth import ApiKeyAuth, BaseAuthStrategy, BasicAuth, BearerAuth, MultiHeaderAuth, NoAuth, TokenAuth
from .client import ResilientHttpClient
from .middleware import MiddlewareChain, OnErrorCallback, OnRequestCallback, OnResponseCallback
from .rate_limit import RateLimiter
from .retry import RetryPolicy

__all__ = [
    "ApiKeyAuth",
    "BaseAuthStrategy",
    "BasicAuth",
    "BearerAuth",
    "MiddlewareChain",
    "MultiHeaderAuth",
    "NoAuth",
    "OnErrorCallback",
    "OnRequestCallback",
    "OnResponseCallback",
    "RateLimiter",
    "ResilientHttpClient",
    "RetryPolicy",
    "TokenAuth",
]
