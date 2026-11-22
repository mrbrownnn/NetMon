"""Repository abstraction (NFR-07) + in-memory implementation for tests."""
from __future__ import annotations

import itertools
import threading
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

T = TypeVar("T")


class Repository(ABC, Generic[T]):
    @abstractmethod
    def get(self, id: int) -> T | None: ...

    @abstractmethod
    def list(self) -> list[T]: ...

    @abstractmethod
    def add(self, obj: T) -> T: ...

    @abstractmethod
    def update(self, obj: T) -> T: ...

    @abstractmethod
    def delete(self, id: int) -> None: ...


class InMemoryRepository(Repository[T]):
    """Stores objects that have an `id` attribute; assigns ids on add when id is None."""

    def __init__(self) -> None:
        self._items: dict[int, T] = {}
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def get(self, id: int) -> T | None:
        return self._items.get(id)

    def list(self) -> list[T]:
        return list(self._items.values())

    def add(self, obj: T) -> T:
        with self._lock:
            if getattr(obj, "id", None) is None:
                obj.id = next(self._seq)  # type: ignore[attr-defined]
            if obj.id in self._items:  # type: ignore[attr-defined]
                raise ValueError(f"duplicate id {obj.id}")  # type: ignore[attr-defined]
            self._items[obj.id] = obj  # type: ignore[attr-defined]
        return obj

    def update(self, obj: T) -> T:
        with self._lock:
            if obj.id not in self._items:  # type: ignore[attr-defined]
                raise KeyError(obj.id)  # type: ignore[attr-defined]
            self._items[obj.id] = obj  # type: ignore[attr-defined]
        return obj

    def delete(self, id: int) -> None:
        with self._lock:
            self._items.pop(id, None)


InMemoryDeviceRepository = InMemorySensorRepository = InMemoryAlertRepository = InMemoryRepository
