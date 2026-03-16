from __future__ import annotations

import json
import logging

from playwright.sync_api import sync_playwright

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Fetcher, ProviderConfig, ProviderFetchContext, ProviderFetchPayload
from app.providers.mitsuuroko_gas.auth import MitsuurokoGasAuthenticator


logger = logging.getLogger(__name__)


class MitsuurokoGasPageFetcher(Fetcher):
    def __init__(self, authenticator: MitsuurokoGasAuthenticator) -> None:
        self._authenticator = authenticator

    def fetch(self, config: ProviderConfig, context: ProviderFetchContext) -> ProviderFetchPayload:
        charge_url = config.extra.get("gas_charge_url") if config.extra else config.target_url
        usage_url = config.extra.get("gas_usage_url") if config.extra else None
        if not charge_url:
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                "MITSUUROKO_GAS_CHARGE_URL is empty. Set the gas charge page URL in the environment.",
            )

        provider_dir = context.snapshots_dir / "mitsuuroko_gas"
        provider_dir.mkdir(parents=True, exist_ok=True)
        timestamp = context.run_started_at.strftime("%Y%m%d_%H%M%S")
        charge_html_path = provider_dir / f"charge_page_{timestamp}.html"
        usage_html_path = provider_dir / f"usage_page_{timestamp}.html"
        screenshot_path = provider_dir / f"gas_page_{timestamp}.png"
        json_path = provider_dir / f"page_meta_{timestamp}.json"

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=config.headless)
                browser_context = browser.new_context()
                page = browser_context.new_page()
                self._authenticator.login(page, config, context)

                logger.info("Navigating to Mitsuuroko gas charge page.")
                page.goto(charge_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                charge_html = page.content()
                charge_html_path.write_text(charge_html, encoding="utf-8")
                page.screenshot(path=str(screenshot_path), full_page=True)

                usage_html = None
                if usage_url:
                    logger.info("Navigating to Mitsuuroko gas consumption page.")
                    page.goto(usage_url, wait_until="domcontentloaded")
                    page.wait_for_load_state("networkidle")
                    usage_html = page.content()
                    usage_html_path.write_text(usage_html, encoding="utf-8")

                json_path.write_text(
                    json.dumps(
                        {
                            "login_url": config.login_url,
                            "charge_url": charge_url,
                            "usage_url": usage_url,
                            "charge_html_path": str(charge_html_path),
                            "usage_html_path": str(usage_html_path) if usage_html else None,
                            "screenshot_path": str(screenshot_path),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                browser_context.close()
                browser.close()
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                f"Failed to fetch Mitsuuroko gas page. {exc}",
            ) from exc

        return ProviderFetchPayload(
            html=charge_html,
            source_url=charge_url,
            html_snapshot_path=str(charge_html_path),
            screenshot_path=str(screenshot_path),
            auxiliary_data={
                "charge_html": charge_html,
                "usage_html": usage_html,
                "charge_url": charge_url,
                "usage_url": usage_url,
                "charge_html_path": str(charge_html_path),
                "usage_html_path": str(usage_html_path) if usage_html else None,
            },
        )
