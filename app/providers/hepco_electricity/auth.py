from __future__ import annotations

import logging
from typing import Any

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Authenticator, ProviderConfig, ProviderFetchContext


logger = logging.getLogger(__name__)


class HepcoAuthenticator(Authenticator):
    USERNAME_SELECTORS = (
        "#LoginId",
        "#loginId",
        "input[name='LoginId']",
        "input[name='loginId']",
        "input[name='UserId']",
        "input[type='email']",
        "input[type='text']",
    )
    PASSWORD_SELECTORS = (
        "#Password",
        "#password",
        "input[name='Password']",
        "input[name='password']",
        "input[type='password']",
    )
    SUBMIT_SELECTORS = (
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('ログイン')",
        "a:has-text('ログイン')",
        ".btn-login",
    )

    def login(self, page: Any, config: ProviderConfig, context: ProviderFetchContext) -> None:
        if not config.username or not config.password:
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                "HEPCO credentials are missing. Check HEPCO_LOGIN_ID and HEPCO_PASSWORD.",
            )

        provider_dir = context.snapshots_dir / "hepco_electricity"
        provider_dir.mkdir(parents=True, exist_ok=True)
        timestamp = context.run_started_at.strftime("%Y%m%d_%H%M%S")

        try:
            logger.info("Opening HEPCO login page.")
            page.goto(config.login_url, wait_until="domcontentloaded")
            page.screenshot(
                path=str(provider_dir / f"01_pre_login_{timestamp}.png"),
                full_page=True,
            )
            self._fill_first(page, self.USERNAME_SELECTORS, config.username, "login ID")
            self._fill_first(page, self.PASSWORD_SELECTORS, config.password, "password")
            self._click_first(page, self.SUBMIT_SELECTORS, "submit button")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.screenshot(
                path=str(provider_dir / f"02_post_login_{timestamp}.png"),
                full_page=True,
            )
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - exercised in integration usage
            screenshot_path = provider_dir / f"login_failed_{timestamp}.png"
            html_path = provider_dir / f"login_failed_{timestamp}.html"
            try:
                html_path.write_text(page.content(), encoding="utf-8")
            except Exception:
                logger.exception("Failed to persist HEPCO login failure HTML.")
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                logger.exception("Failed to capture HEPCO login failure screenshot.")
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                f"HEPCO login flow failed. Verify selectors and credentials. {exc}",
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
                logger.info("Skipping HEPCO selector %s for %s.", selector, field_name)
        raise ProviderError(
            ErrorCode.LOGIN_FAILED,
            f"Could not find a HEPCO {field_name} field. Update selector candidates.",
        )

    def _click_first(self, page: Any, selectors: tuple[str, ...], target_name: str) -> None:
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if locator.count():
                    locator.click()
                    return
            except Exception:
                logger.info("Skipping HEPCO selector %s for %s.", selector, target_name)
        raise ProviderError(
            ErrorCode.LOGIN_FAILED,
            f"Could not find a HEPCO {target_name}. Update selector candidates.",
        )
