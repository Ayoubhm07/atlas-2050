"""Enveloppe de réponse commune à toute l'API."""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Meta(BaseModel):
    total: int | None = None
    page: int | None = None
    limit: int | None = None
    sources: tuple[str, ...] = ()


class Envelope(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None
    meta: Meta = Meta()


def ok(data: T, meta: Meta | None = None) -> Envelope[T]:
    return Envelope[T](success=True, data=data, meta=meta or Meta())


def fail(message: str) -> Envelope[None]:
    return Envelope[None](success=False, error=message)
