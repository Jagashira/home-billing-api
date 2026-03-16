from __future__ import annotations

from app.config import get_settings
from app.providers.base.interfaces import Provider, ProviderFetchContext, ProviderFetchResult, ProviderMetadata
from app.providers.hepco_electricity.config import build_hepco_config
from app.providers.hepco_electricity.fetch import HepcoPageFetcher
from app.providers.hepco_electricity.parser import HepcoBillingParser


class HepcoElectricityProvider(Provider):
    metadata = ProviderMetadata(
        name="hepco_electricity",
        display_name="HEPCO Electricity",
        service_type="electricity",
        description="HEPCO portal billing provider with monthly CSV download and parsing.",
    )

    def __init__(self, fetcher: HepcoPageFetcher, parser: HepcoBillingParser) -> None:
        self._fetcher = fetcher
        self._parser = parser

    def is_enabled(self) -> bool:
        settings = get_settings()
        return bool(settings.hepco_login_id and settings.hepco_password and settings.hepco_target_url)

    def fetch_billing(self, context: ProviderFetchContext) -> ProviderFetchResult:
        settings = get_settings()
        config = build_hepco_config(settings)
        payload = self._fetcher.fetch(config, context)
        return self._parser.parse(payload)
