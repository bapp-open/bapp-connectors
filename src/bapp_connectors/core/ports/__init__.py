"""Port interfaces (contracts) for each provider family."""

from .ads import AdsPort
from .appstore import AppStorePort
from .base import BasePort
from .courier import CourierPort
from .dns import DnsPort
from .email import EmailPort
from .feed import FeedPort
from .hosting import HostingPort
from .llm import LLMPort
from .messaging import MessagingPort
from .network import NetworkPort
from .payment import PaymentPort
from .shop import ShopPort
from .social import SocialPort
from .storage import FileInfo, StoragePort

__all__ = [
    "AdsPort",
    "AppStorePort",
    "BasePort",
    "CourierPort",
    "DnsPort",
    "EmailPort",
    "FeedPort",
    "FileInfo",
    "HostingPort",
    "LLMPort",
    "MessagingPort",
    "NetworkPort",
    "PaymentPort",
    "ShopPort",
    "SocialPort",
    "StoragePort",
]
