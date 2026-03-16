from __future__ import annotations

import logging
from typing import Any

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import Authenticator, ProviderConfig, ProviderFetchContext


logger = logging.getLogger(__name__)


class SoftbankAuthenticator(Authenticator):
    def login(self, page: Any, config: ProviderConfig, context: ProviderFetchContext) -> None:
        if not config.username or not config.password:
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                "SoftBank credentials are missing. Check SOFTBANK_SID and SOFTBANK_PASSWORD.",
            )

        try:
            provider_dir = context.snapshots_dir / "softbank_internet"
            provider_dir.mkdir(parents=True, exist_ok=True)
            timestamp = context.run_started_at.strftime("%Y%m%d_%H%M%S")

            logger.info("Opening SoftBank login page.")
            page.goto(config.login_url, wait_until="domcontentloaded")
            page.screenshot(
                path=str(provider_dir / f"01_pre_login_{timestamp}.png"),
                full_page=True,
            )
            page.wait_for_selector("#sid", state="visible")
            page.wait_for_selector("#password", state="visible")

            # The current login page uses #sid and #password.
            # TODO: Re-check selectors if SoftBank changes the login DOM.
            page.fill("#sid", config.username)
            page.fill("#password", config.password)
            visible_login_button = page.locator("a.login_btn:visible").first
            if visible_login_button.count():
                visible_login_button.click()
            else:
                # Fallback to form submit when the styled anchor cannot be interacted with.
                page.locator("form[name='sidLoginForm']").evaluate("(form) => form.submit()")
            self._wait_for_login_transition(page)
            page.screenshot(
                path=str(provider_dir / f"02_post_login_{timestamp}.png"),
                full_page=True,
            )
        except Exception as exc:  # pragma: no cover - exercised in integration usage
            screenshot_path = provider_dir / f"login_failed_{timestamp}.png"
            html_path = provider_dir / f"login_failed_{timestamp}.html"
            try:
                html_path.write_text(page.content(), encoding="utf-8")
            except Exception:
                logger.exception("Failed to persist login failure HTML.")
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
            except Exception:
                logger.exception("Failed to capture login failure screenshot.")
            raise ProviderError(
                ErrorCode.LOGIN_FAILED,
                f"SoftBank login flow failed. Verify selectors and credentials. {exc}",
                screenshot_path=str(screenshot_path),
                html_snapshot_path=str(html_path),
            ) from exc

    def _wait_for_login_transition(self, page: Any) -> None:
        page.wait_for_load_state("domcontentloaded")

        # SoftBank sometimes lands on an intermediate page that says "ログイン中"
        # and requires clicking "次へ" if the redirect does not continue automatically.
        next_link = page.locator("text=次へ").first
        try:
            if next_link.is_visible(timeout=5_000):
                logger.info("Detected post-login transition page. Clicking '次へ'.")
                next_link.click()
        except Exception:
            logger.info("No explicit '次へ' transition was required.")

        page.wait_for_load_state("networkidle")

        try:
            page.wait_for_function(
                """
                () => {
                    const href = window.location.href;
                    const bodyText = document.body ? document.body.innerText : "";
                    return !href.includes('/AUT/sid/login') && !bodyText.includes('ログイン中');
                }
                """,
                timeout=20_000,
            )
        except Exception:
            logger.info("Login transition page did not fully resolve within timeout. Continuing with current session.")
