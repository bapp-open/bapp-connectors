"""
SAGA Web raw wire shapes (not DTOs).

Every JSON answer is the envelope below; SAGA sends the error text in ``message`` on some
endpoints and in ``error`` on others. Import reports (HTTP 207/422) and the XML reports
(``<Situatie>``, ``<Balanta>``, ``<Articol>``) are parsed straight from text in ``mappers``.
"""

from __future__ import annotations

from pydantic import BaseModel


class SagaEnvelope(BaseModel):
    success: bool
    message: str = ""
    error: str = ""
    data: str = ""
