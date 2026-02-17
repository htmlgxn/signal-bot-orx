from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str | None = None
    date: str | None = None
    image_url: str | None = None


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search(self, query: str) -> list[SearchResult]: ...
