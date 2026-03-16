from __future__ import annotations

from functools import lru_cache

from app.providers.base import ProviderRegistry
from app.providers.softbank_internet.auth import SoftbankAuthenticator
from app.providers.softbank_internet.fetch import SoftbankPageFetcher
from app.providers.softbank_internet.parser import SoftbankBillingParser
from app.providers.softbank_internet.provider import SoftbankInternetProvider


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(
        SoftbankInternetProvider(
            fetcher=SoftbankPageFetcher(authenticator=SoftbankAuthenticator()),
            parser=SoftbankBillingParser(),
        )
    )
    return registry

