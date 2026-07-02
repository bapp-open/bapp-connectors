"""Port interfaces (contracts) for each provider family."""

from .ads import AdsPort
from .base import BasePort
from .courier import CourierPort
from .email import EmailPort
from .feed import FeedPort
from .llm import LLMPort
from .messaging import MessagingPort
from .payment import PaymentPort
from .shop import ShopPort
from .social import SocialPort
from .storage import FileInfo, StoragePort

__all__ = [
    "AdsPort",
    "BasePort",
    "CourierPort",
    "EmailPort",
    "FeedPort",
    "FileInfo",
    "LLMPort",
    "MessagingPort",
    "PaymentPort",
    "ShopPort",
    "SocialPort",
    "StoragePort",
]
