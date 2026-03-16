from __future__ import annotations

from app.config import get_settings
from app.providers.base.interfaces import Provider, ProviderFetchContext, ProviderFetchResult, ProviderMetadata
from app.providers.softbank_internet.config import build_softbank_config
from app.providers.softbank_internet.fetch import SoftbankPageFetcher
from app.providers.softbank_internet.parser import SoftbankBillingParser


class SoftbankInternetProvider(Provider):
    metadata = ProviderMetadata(
        name="softbank_internet",
        display_name="SoftBank Internet",
        service_type="internet",
        description="SoftBank internet billing provider via Playwright login and page parsing.",
    )

    def __init__(self, fetcher: SoftbankPageFetcher, parser: SoftbankBillingParser) -> None:
        self._fetcher = fetcher
        self._parser = parser

    def is_enabled(self) -> bool:
        settings = get_settings()
        return bool(settings.softbank_sid and settings.softbank_password and settings.softbank_target_url)

    def fetch_billing(self, context: ProviderFetchContext) -> ProviderFetchResult:
        settings = get_settings()
        config = build_softbank_config(settings)
        payload = self._fetcher.fetch(config, context)
        return self._parser.parse(payload)

