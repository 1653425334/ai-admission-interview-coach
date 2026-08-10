"""Storage abstraction used by document services."""

from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    def get(self, key: str) -> bytes:
        """Read one private object after ownership has already been checked."""
        ...

    def put(self, key: str, content: bytes, content_type: str) -> None:
        """Store a new private object without overwriting an existing object."""
        ...

    def delete(self, key: str) -> None:
        """Delete a private object."""
        ...
