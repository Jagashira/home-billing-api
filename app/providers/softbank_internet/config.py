from __future__ import annotations

from app.config import Settings
from app.providers.base.interfaces import ProviderConfig


def build_softbank_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        headless=settings.headless,
        login_url=settings.softbank_login_url,
        target_url=settings.softbank_target_url,
        username=settings.softbank_sid,
        password=settings.softbank_password,
    )
