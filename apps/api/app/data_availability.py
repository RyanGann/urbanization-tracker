from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class Availability(StrEnum):
    READY = "ready"
    UNINITIALIZED = "uninitialized"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CollectionRead(Generic[T]):
    """A typed read result where an empty ready collection remains meaningful."""

    availability: Availability
    items: T | None = None

    def require_ready(self, *, collection: str) -> T:
        if self.availability is Availability.READY and self.items is not None:
            return self.items
        raise DataUnavailableError(collection=collection, availability=self.availability)


class DataUnavailableError(RuntimeError):
    """A safe public error for missing or failed canonical data."""

    def __init__(self, *, collection: str, availability: Availability) -> None:
        self.collection = collection
        self.availability = availability
        super().__init__(f"Canonical collection '{collection}' is {availability.value}.")
