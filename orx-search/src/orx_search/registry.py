from __future__ import annotations

from .base import SearchProvider

_PROVIDERS: dict[str, type[SearchProvider]] = {}


def register(cls: type[SearchProvider]) -> type[SearchProvider]:
    """Decorator to register a search provider."""
    # Instantiating to check name might be risky if init does heavy lifting,
    # but protocols don't enforce static name.
    # We'll assume the class has a 'name' attribute for now, or use the class instance later.
    # Actually, let's register by the name attribute on the class if possible, or require it.
    if hasattr(cls, "name"):
        _PROVIDERS[cls.name] = cls
    return cls


def get_provider(name: str) -> type[SearchProvider]:
    """Get a provider class by name."""
    if name not in _PROVIDERS:
        raise ValueError(
            f"Provider '{name}' not found. Available: {list(_PROVIDERS.keys())}"
        )
    return _PROVIDERS[name]


def list_providers() -> list[str]:
    """List available provider names."""
    return list(_PROVIDERS.keys())


def get_all_providers() -> dict[str, type[SearchProvider]]:
    return _PROVIDERS.copy()
