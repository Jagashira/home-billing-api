from __future__ import annotations

import json
import logging

from playwright.sync_api import sync_playwright

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Fetcher, ProviderConfig, ProviderFetchContext, ProviderFetchPayload
from app.providers.softbank_internet.auth import SoftbankAuthenticator


logger = logging.getLogger(__name__)


class SoftbankPageFetcher(Fetcher):
    def __init__(self, authenticator: SoftbankAuthenticator) -> None:
        self._authenticator = authenticator

    def fetch(self, config: ProviderConfig, context: ProviderFetchContext) -> ProviderFetchPayload:
        if not config.target_url:
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                "SOFTBANK_TARGET_URL is empty. Set the billing page URL in the environment.",
            )

        provider_dir = context.snapshots_dir / "softbank_internet"
        provider_dir.mkdir(parents=True, exist_ok=True)
        timestamp = context.run_started_at.strftime("%Y%m%d_%H%M%S")
        html_path = provider_dir / f"billing_page_{timestamp}.html"
        screenshot_path = provider_dir / f"billing_page_{timestamp}.png"
        json_path = provider_dir / f"page_meta_{timestamp}.json"
        target_screenshot_path = provider_dir / f"03_target_page_{timestamp}.png"
        storage_state_path = provider_dir / f"session_state_{timestamp}.json"

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=config.headless)
                browser_context = browser.new_context()
                page = browser_context.new_page()
                self._authenticator.login(page, config, context)
                browser_context.storage_state(path=str(storage_state_path))

                logger.info("Navigating to SoftBank target billing page with authenticated browser context.")
                page.goto(config.target_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                html = page.content()
                page.screenshot(path=str(target_screenshot_path), full_page=True)
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(html, encoding="utf-8")
                cookies = browser_context.cookies()
                json_path.write_text(
                    json.dumps(
                        {
                            "login_url": config.login_url,
                            "target_url": config.target_url,
                            "current_url_after_login": page.url,
                            "pre_login_screenshot": str(provider_dir / f"01_pre_login_{timestamp}.png"),
                            "post_login_screenshot": str(provider_dir / f"02_post_login_{timestamp}.png"),
                            "target_page_screenshot": str(target_screenshot_path),
                            "session_state_path": str(storage_state_path),
                            "cookies_count": len(cookies),
                            "cookie_names": [cookie["name"] for cookie in cookies],
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
        except Exception as exc:  # pragma: no cover - exercised in integration usage
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                f"Failed to fetch SoftBank billing page. {exc}",
            ) from exc

        return ProviderFetchPayload(
            html=html,
            source_url=config.target_url,
            html_snapshot_path=str(html_path),
            screenshot_path=str(screenshot_path),
        )
