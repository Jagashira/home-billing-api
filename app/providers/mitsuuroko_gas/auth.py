from __future__ import annotations

import logging
from typing import Any

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Authenticator, ProviderConfig, ProviderFetchContext


logger = logging.getLogger(__name__)


class MitsuurokoGasAuthenticator(Authenticator):
    USERNAME_SELECTORS = (
        "input[name='login_id']",
        "input[name='member_id']",
        "input[name='id']",
        "input[type='text']",
        "input[type='email']",
    )
    PASSWORD_SELECTORS = (
        "input[name='password']",
        "input[type='password']",
    )
    SUBMIT_SELECTORS = (
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('ログイン')",
        "a:has-text('ログイン')",
    )

    def login(self, page: Any, config: ProviderConfig, context: ProviderFetchContext) -> None:
        if not config.username or not config.password:
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                "Mitsuuroko credentials are missing. Check MITSUUROKO_LOGIN_ID and MITSUUROKO_PASSWORD.",
            )

        provider_dir = context.snapshots_dir / "mitsuuroko_gas"
        provider_dir.mkdir(parents=True, exist_ok=True)
        timestamp = context.run_started_at.strftime("%Y%m%d_%H%M%S")
        try:
            logger.info("Opening Mitsuuroko login page.")
            page.goto(config.login_url, wait_until="domcontentloaded")
            page.screenshot(path=str(provider_dir / f"01_pre_login_{timestamp}.png"), full_page=True)
            self._fill_first(page, self.USERNAME_SELECTORS, config.username, "login ID")
            self._fill_first(page, self.PASSWORD_SELECTORS, config.password, "password")
            self._click_first(page, self.SUBMIT_SELECTORS, "submit button")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(provider_dir / f"02_post_login_{timestamp}.png"), full_page=True)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover
            screenshot_path = provider_dir / f"login_failed_{timestamp}.png"
            html_path = provider_dir / f"login_failed_{timestamp}.html"
            try:
                html_path.write_text(page.content(), encoding="utf-8")
            except Exception:
                logger.exception("Failed to persist Mitsuuroko login failure HTML.")
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                logger.exception("Failed to capture Mitsuuroko login failure screenshot.")
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                f"Mitsuuroko login flow failed. Verify selectors and credentials. {exc}",
                screenshot_path=str(screenshot_path),
                html_snapshot_path=str(html_path),
            ) from exc

    def _fill_first(self, page: Any, selectors: tuple[str, ...], value: str, field_name: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count():
                    locator.fill(value)
                    return
            except Exception:
                logger.info("Skipping Mitsuuroko selector %s for %s.", selector, field_name)
        raise ProviderError(
            ErrorCode.LOGIN_FAILED,
            f"Could not find a Mitsuuroko {field_name} field. Update selector candidates.",
        )

    def _click_first(self, page: Any, selectors: tuple[str, ...], target_name: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count():
                    locator.click()
                    return
            except Exception:
                logger.info("Skipping Mitsuuroko selector %s for %s.", selector, target_name)
        raise ProviderError(
            ErrorCode.LOGIN_FAILED,
            f"Could not find a Mitsuuroko {target_name}. Update selector candidates.",
        )
