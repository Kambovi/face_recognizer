from __future__ import annotations

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str
    code: str


class Page(BaseModel):
    total: int
    page: int
    page_size: int
