"""Modele Pydantic pentru payload-urile JSON Google (Android Publisher). CSV-urile raman dict-uri."""

from __future__ import annotations

from pydantic import BaseModel


class VoidedPurchase(BaseModel):
    purchaseToken: str = ""
    orderId: str = ""
    purchaseTimeMillis: str = "0"
    voidedTimeMillis: str = "0"
    voidedSource: int | None = None
    voidedReason: int | None = None


class PubSubMessage(BaseModel):
    """Corpul unui push Pub/Sub: {"message": {"data": base64, "messageId": ...}, "subscription": ...}."""

    data: str = ""
    messageId: str = ""
    publishTime: str = ""
    attributes: dict = {}
