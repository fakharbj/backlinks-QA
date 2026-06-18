"""Shared schema primitives: base config, keyset pagination envelope."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class KeysetPage(BaseModel, Generic[T]):
    """Cursor-paginated envelope — constant-time at 1M rows (Arch §10)."""

    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
    total: int | None = None  # populated only when explicitly requested (expensive)


class Message(BaseModel):
    message: str


class IdResponse(BaseModel):
    id: str
