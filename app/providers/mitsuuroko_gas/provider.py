from __future__ import annotations

from app.config import get_settings
from app.providers.base.interfaces import Provider, ProviderFetchContext, ProviderFetchResult, ProviderMetadata
from app.providers.mitsuuroko_gas.config import build_mitsuuroko_gas_config
from app.providers.mitsuuroko_gas.fetch import MitsuurokoGasPageFetcher
from app.providers.mitsuuroko_gas.parser import MitsuurokoGasParser


class MitsuurokoGasProvider(Provider):
    metadata = ProviderMetadata(
        name="mitsuuroko_gas",
        display_name="Mitsuuroko Gas",
        service_type="gas",
        description="Mitsuuroko Enecheck gas monthly usage and charge provider.",
    )

    def __init__(self, fetcher: MitsuurokoGasPageFetcher, parser: MitsuurokoGasParser) -> None:
        self._fetcher = fetcher
        self._parser = parser

    def is_enabled(self) -> bool:
        settings = get_settings()
        return bool(
            settings.mitsuuroko_login_id
            and settings.mitsuuroko_password
            and settings.mitsuuroko_gas_charge_url
        )

    def fetch_billing(self, context: ProviderFetchContext) -> ProviderFetchResult:
        settings = get_settings()
        config = build_mitsuuroko_gas_config(settings)
        payload = self._fetcher.fetch(config, context)
        return self._parser.parse(payload)
