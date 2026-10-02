"""Modele Pydantic pentru payload-urile brute Apple (JSON:API). Rapoartele TSV raman dict-uri."""

from __future__ import annotations

from datetime import datetime  # noqa: F401 — convenție: tipurile folosite in modele sunt importate la nivel de modul

from pydantic import BaseModel


class AppleResource(BaseModel):
    """Un element JSON:API: {"type": ..., "id": ..., "attributes": {...}, "relationships": {...}}."""

    type: str = ""
    id: str = ""
    attributes: dict = {}
    relationships: dict = {}


class AppleListResponse(BaseModel):
    data: list[AppleResource] = []
    included: list[AppleResource] = []
    links: dict = {}
