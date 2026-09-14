"""Pydantic models for the raw payloads our PHP snippets return (NOT DTOs)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RawInterface(BaseModel):
    ref: str
    descr: str = ""
    ip: str = ""
    subnet: str | int | None = None
    dhcp_from: str = ""
    dhcp_to: str = ""
    dhcp_enabled: bool = False


class RawLease(BaseModel):
    ip: str
    mac: str = ""
    hostname: str = ""
    online: str = ""
    starts: str = ""
    ends: str = ""
    act: str = ""
    type: str = ""
    cid: str = ""


class RawArpEntry(BaseModel):
    ip: str
    mac: str
    iface: str = ""


class RawDeviceInfo(BaseModel):
    hostname: str = ""
    domain: str = ""
    version: str = ""
    platform: str = ""
    uptime: int | None = None
    extra: dict = Field(default_factory=dict)
