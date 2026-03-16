from __future__ import annotations

from functools import lru_cache

from app.providers.base import ProviderRegistry
from app.providers.hepco_electricity.auth import HepcoAuthenticator
from app.providers.hepco_electricity.fetch import HepcoPageFetcher
from app.providers.hepco_electricity.parser import HepcoBillingParser
from app.providers.hepco_electricity.provider import HepcoElectricityProvider
from app.providers.mitsuuroko_gas.auth import MitsuurokoGasAuthenticator
from app.providers.mitsuuroko_gas.fetch import MitsuurokoGasPageFetcher
from app.providers.mitsuuroko_gas.parser import MitsuurokoGasParser
from app.providers.mitsuuroko_gas.provider import MitsuurokoGasProvider
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
    registry.register(
        HepcoElectricityProvider(
            fetcher=HepcoPageFetcher(authenticator=HepcoAuthenticator()),
            parser=HepcoBillingParser(),
        )
    )
    registry.register(
        MitsuurokoGasProvider(
            fetcher=MitsuurokoGasPageFetcher(authenticator=MitsuurokoGasAuthenticator()),
            parser=MitsuurokoGasParser(),
        )
    )
    return registry
