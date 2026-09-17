"""Pydantic models for raw UAPI payloads. These are NOT DTOs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class UapiEnvelope(BaseModel):
    """Every UAPI response, success or failure, arrives in this shape."""

    status: int = 0
    data: Any = None
    errors: list[str] | None = None
    warnings: list[str] | None = None
    messages: list[str] | None = None
    metadata: dict = {}

    @property
    def ok(self) -> bool:
        return self.status == 1

    @property
    def first_error(self) -> str:
        return (self.errors or ["cPanel reported a failure with no message"])[0]


class CpanelResourceUsage(BaseModel):
    """One entry of `ResourceUsage/get_usages`."""

    id: str
    usage: float | int | str | None = None
    maximum: float | int | str | None = None
    """None means unlimited."""
    formatter: str | None = None
    description: str | None = None


class CpanelPop(BaseModel):
    """One entry of `Email/list_pops_with_disk`.

    `diskused`/`diskquota` are MEGABYTES as strings; the underscore-prefixed pair
    is BYTES. Always read the underscore pair.
    """

    email: str
    login: str = ""
    domain: str = ""
    diskused: str | None = None
    diskquota: str | None = None
    raw_disk_used: str | None = Field(default=None, alias="_diskused")
    raw_disk_quota: str | None = Field(default=None, alias="_diskquota")
    diskusedpercent_float: float | None = None
    suspended_login: int | None = None
    suspended_incoming: int | None = None
    """cPanel sends null, not 0, for a mailbox that was never suspended."""

    model_config = {"populate_by_name": True}


class CpanelZoneLine(BaseModel):
    """One line of `DNS/parse_zone`.

    `comment` and `control` lines carry `text_b64`. `record` lines carry structured
    fields and no `text_b64`.
    """

    type: str
    line_index: int
    text_b64: str | None = None
    record_type: str | None = None
    ttl: int | None = None
    dname_raw: str | None = None
    dname_b64: str | None = None
    data_b64: list[str] | None = None
