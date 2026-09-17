"""Pydantic models for the raw payloads our PHP snippets return (NOT DTOs)."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class _RawPayload(BaseModel):
    """Bază pentru payload-urile brute din pfSense.

    PHP/XML-RPC trimite `null` pentru valorile absente (ex. un lease static fără `cid`), iar pydantic
    refuză `None` pe un câmp `str` chiar dacă are valoare implicită — implicitul se aplică doar când
    cheia lipsește. Tratăm `null` ca „lipsește”, ca să cadă pe valoarea implicită a câmpului.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


class RawInterface(_RawPayload):
    ref: str
    descr: str = ""
    ip: str = ""
    subnet: str | int | None = None
    dhcp_from: str = ""
    dhcp_to: str = ""
    dhcp_enabled: bool = False


class RawLease(_RawPayload):
    ip: str
    mac: str = ""
    hostname: str = ""
    online: str = ""
    starts: str = ""
    ends: str = ""
    act: str = ""
    type: str = ""
    cid: str = ""


class RawArpEntry(_RawPayload):
    ip: str
    mac: str
    iface: str = ""


class RawDeviceInfo(_RawPayload):
    hostname: str = ""
    domain: str = ""
    version: str = ""
    platform: str = ""
    uptime: int | None = None
    extra: dict = Field(default_factory=dict)
