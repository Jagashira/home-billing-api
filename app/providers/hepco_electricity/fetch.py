from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Fetcher, ProviderConfig, ProviderFetchContext, ProviderFetchPayload
from app.providers.hepco_electricity.auth import HepcoAuthenticator


logger = logging.getLogger(__name__)


class HepcoPageFetcher(Fetcher):
    def __init__(self, authenticator: HepcoAuthenticator) -> None:
        self._authenticator = authenticator

    def fetch(self, config: ProviderConfig, context: ProviderFetchContext) -> ProviderFetchPayload:
        if not config.target_url:
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                "HEPCO_TARGET_URL is empty. Set the billing page URL in the environment.",
            )

        provider_dir = context.snapshots_dir / "hepco_electricity"
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
                browser_context = browser.new_context(accept_downloads=True)
                page = browser_context.new_page()
                self._authenticator.login(page, config, context)
                browser_context.storage_state(path=str(storage_state_path))

                logger.info("Navigating to HEPCO billing page with authenticated browser context.")
                page.goto(config.target_url, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle")
                html = page.content()
                page.screenshot(path=str(target_screenshot_path), full_page=True)
                page.screenshot(path=str(screenshot_path), full_page=True)
                html_path.write_text(html, encoding="utf-8")

                billing_pages = self._collect_billing_pages(page, browser_context, provider_dir, timestamp)
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
                            "billing_page_count": len(billing_pages),
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
                f"Failed to fetch HEPCO billing page. {exc}",
            ) from exc

        return ProviderFetchPayload(
            html=html,
            source_url=config.target_url,
            html_snapshot_path=str(html_path),
            screenshot_path=str(screenshot_path),
            auxiliary_data={"billing_pages": billing_pages},
        )

    def _collect_billing_pages(
        self,
        page: Page,
        browser_context: BrowserContext,
        provider_dir: Path,
        timestamp: str,
    ) -> list[dict[str, str | None]]:
        self._wait_for_billing_page_ready(page)
        option_values = page.eval_on_selector_all(
            "#Electric_SelectedHistoryIndex option",
            "(options) => options.map((option) => ({ value: option.value, label: option.textContent?.trim() || '' }))",
        )
        current_value = page.locator("#Electric_SelectedHistoryIndex").input_value()

        csv_dir = provider_dir / "csv"
        csv_dir.mkdir(parents=True, exist_ok=True)
        pages: list[dict[str, str | None]] = []
        for option in option_values:
            value = str(option["value"])
            if value != current_value:
                with page.expect_navigation(wait_until="domcontentloaded"):
                    page.select_option("#Electric_SelectedHistoryIndex", value=value)
                self._wait_for_billing_page_ready(page)
                current_value = value
            else:
                self._wait_for_billing_page_ready(page)
            page_html = page.content()
            page_path = provider_dir / f"billing_page_{value}_{timestamp}.html"
            page_path.write_text(page_html, encoding="utf-8")

            soup = BeautifulSoup(page_html, "html.parser")
            selected_option = soup.select_one("#Electric_SelectedHistoryIndex option[selected]")
            billing_month = selected_option.get_text(strip=True) if selected_option else str(option["label"]).strip()
            csv_url = self._extract_link(page, "a[href*='BillingInfoCsvByMonth']")
            pdf_url = self._extract_link(page, "a[href*='BillingInfoPdf']")
            csv_path = None
            if csv_url:
                csv_path = str(self._download_csv(browser_context, csv_url, csv_dir / f"billing_{value}_{timestamp}.csv"))
            pages.append(
                {
                    "billing_month": billing_month,
                    "month_value": value,
                    "source_url": page.url,
                    "html_snapshot_path": str(page_path),
                    "csv_url": csv_url,
                    "csv_path": csv_path,
                    "pdf_url": pdf_url,
                }
            )
        return pages

    def _extract_link(self, page: Page, selector: str) -> str | None:
        href = page.locator(selector).first.get_attribute("href")
        if not href:
            return None
        return urljoin(page.url, href)

    def _download_csv(self, browser_context: BrowserContext, csv_url: str, destination: Path) -> Path:
        response = browser_context.request.get(csv_url)
        if not response.ok:
            raise ProviderError(
                ErrorCode.TARGET_PAGE_UNREACHABLE,
                f"Failed to download HEPCO CSV. status={response.status} url={csv_url}",
            )
        destination.write_bytes(response.body())
        return destination

    def _wait_for_billing_page_ready(self, page: Page) -> None:
        page.wait_for_selector("#Electric_SelectedHistoryIndex")
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_load_state("networkidle")
        page.wait_for_function("() => document.readyState === 'complete'")
