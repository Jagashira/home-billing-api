from __future__ import annotations

from app.config import Settings
from app.providers.base.interfaces import ProviderConfig


def build_mitsuuroko_gas_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        headless=settings.headless,
        login_url=settings.mitsuuroko_login_url,
        target_url=settings.mitsuuroko_gas_charge_url,
        username=settings.mitsuuroko_login_id,
        password=settings.mitsuuroko_password,
        extra={
            "gas_usage_url": settings.mitsuuroko_gas_usage_url,
            "gas_charge_url": settings.mitsuuroko_gas_charge_url,
        },
    )
