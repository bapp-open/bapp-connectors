"""
Raw Company Store API payload shapes. Not DTOs: conversion happens in mappers.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SyncItemResult(BaseModel):
    """One positional entry of a CatalogSyncTask response (status: created | updated | error)."""

    index: int
    id: str
    status: str
    error: str = ""
    code: str = ""


class SyncTaskResponse(BaseModel):
    categories: list[SyncItemResult] = Field(default_factory=list)
    products: list[SyncItemResult] = Field(default_factory=list)
    rules_applied: bool = False
    webhook_applied: bool = False
    customers_applied: bool = False
