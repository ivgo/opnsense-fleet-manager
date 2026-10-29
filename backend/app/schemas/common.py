from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.pagination import PageMeta

T = TypeVar("T")

__all__ = [
    "ORMModel",
    "Message",
    "ErrorBody",
    "ErrorResponse",
    "PageMeta",
    "PageResponse",
    "IdResponse",
    "BulkResult",
    "TimestampedModel",
]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Message(BaseModel):
    message: str
    code: str | None = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PageResponse(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta


class IdResponse(BaseModel):
    id: UUID


class BulkResult(BaseModel):
    ok: list[UUID] = Field(default_factory=list)
    failed: list[dict[str, Any]] = Field(default_factory=list)


class TimestampedModel(ORMModel):
    id: UUID
    created_at: datetime
    updated_at: datetime
