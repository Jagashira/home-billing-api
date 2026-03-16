from __future__ import annotations

from collections.abc import Iterable

from app.providers.base.interfaces import Provider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        self._providers[provider.metadata.name] = provider

    def get(self, provider_name: str) -> Provider:
        if provider_name not in self._providers:
            raise KeyError(f"Provider '{provider_name}' is not registered.")
        return self._providers[provider_name]

    def list(self) -> list[Provider]:
        return list(self._providers.values())

    def iter_enabled(self) -> Iterable[Provider]:
        return (provider for provider in self._providers.values() if provider.is_enabled())

