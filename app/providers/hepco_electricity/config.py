from __future__ import annotations

from app.config import Settings
from app.providers.base.interfaces import ProviderConfig


def build_hepco_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        headless=settings.headless,
        login_url=settings.hepco_login_url,
        target_url=settings.hepco_target_url,
        username=settings.hepco_login_id,
        password=settings.hepco_password,
    )
