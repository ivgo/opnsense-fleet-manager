from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    size: int = Field(50, ge=1, le=500)
    sort: str | None = None
    order: str = "desc"

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    pages: int


class Page(BaseModel, Generic[T]):
    items: list[T]
    meta: PageMeta


def page_meta(page: int, size: int, total: int) -> PageMeta:
    pages = (total + size - 1) // size if size else 0
    return PageMeta(page=page, size=size, total=total, pages=pages)
