from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from app.timetree.artifacts import (
    capture_failure,
    configure_timetree_logging,
    timestamp_slug,
    write_private_json,
)
from app.timetree.config import TimeTreeConfig
from app.timetree.models import (
    CalendarInfo,
    OwnedEventRecord,
    TestEventSpec,
    utc_now_iso,
)
from app.timetree.ownership import (
    OwnershipError,
    OwnershipRegistry,
    assert_owned_page,
    assert_record_owned,
    assert_safe_event_url,
    build_test_event,
    build_updated_title,
    derive_event_id,
)
from app.timetree.selectors import (
    CALENDAR_LIST_NAMES,
    CONFIRM_DELETE_NAMES,
    CREATE_EVENT_NAMES,
    DELETE_NAMES,
    DESCRIPTION_LABELS,
    EDIT_NAMES,
    MORE_NAMES,
    NOTE_CONFIRM_NAMES,
    NOTE_NAMES,
    SAVE_NAMES,
    SHOW_ONLY_CALENDAR_NAMES,
    SelectorNotFound,
    click_role,
    fill_labeled,
    first_visible,
    role_locator,
    unique_labeled_locator,
    unique_role_locator,
    unique_visible,
)


class AuthenticationRequired(RuntimeError):
    pass


class CalendarNotFound(RuntimeError):
    pass


class EventFormInvalid(RuntimeError):
    pass


EVENT_TITLE_FIELD_SELECTOR = "textarea[name='title'][placeholder='Event title (required)']"


@dataclass(frozen=True)
class AuthAssessment:
    required: bool
    reason: str


class TimeTreeClient:
    def __init__(self, config: TimeTreeConfig) -> None:
        self.config = config
        self.config.ensure_directories()
        self.logger = configure_timetree_logging(config)
        self.registry = OwnershipRegistry(config.registry_path)

    @contextmanager
    def _session(
        self,
        operation: str,
        *,
        use_storage_state: bool = True,
        headless: bool | None = None,
    ) -> Iterator[tuple[Page, BrowserContext]]:
        page: Page | None = None
        try:
            with sync_playwright() as playwright:
                context: BrowserContext | None = None
                browser = None
                trace_started = False
                artifacts: dict[str, str | None] = {}
                browser = playwright.chromium.launch(
                    headless=self.config.headless if headless is None else headless
                )
                context_args: dict[str, Any] = {
                    "locale": "ja-JP",
                    "timezone_id": "Asia/Tokyo",
                    "viewport": {"width": 1440, "height": 1000},
                }
                if use_storage_state and self.config.storage_state_path.exists():
                    context_args["storage_state"] = str(self.config.storage_state_path)
                context = browser.new_context(**context_args)
                if self.config.debug:
                    context.tracing.start(screenshots=True, snapshots=True, sources=False)
                    trace_started = True
                page = context.new_page()
                page.set_default_timeout(self.config.timeout_ms)
                try:
                    yield page, context
                    if use_storage_state and not self._auth_required(page):
                        self._save_storage_state(context)
                except Exception as exc:
                    artifacts = capture_failure(
                        config=self.config,
                        page=page,
                        operation=operation,
                        error=exc,
                    )
                    self.logger.exception(
                        "TIMETREE_ERROR operation=%s url=%s screenshot=%s",
                        operation,
                        artifacts.get("url"),
                        artifacts.get("screenshot"),
                    )
                    raise
                finally:
                    if trace_started:
                        trace_path = self.config.traces_dir / f"{timestamp_slug()}_{operation}.zip"
                        try:
                            context.tracing.stop(path=str(trace_path))
                            trace_path.chmod(0o600)
                        except Exception:
                            self.logger.exception("TIMETREE_ERROR operation=trace_stop")
                    context.close()
                    browser.close()
        except Exception:
            if page is None:
                self.logger.exception(
                    "TIMETREE_ERROR operation=%s url=unavailable screenshot=unavailable",
                    operation,
                )
            raise

    def login(self, *, wait_seconds: int = 600) -> Path:
        if self.config.headless:
            raise RuntimeError(
                "Manual login requires a headed browser. Run with --headed on a trusted GUI computer."
            )
        with self._session("login", use_storage_state=False, headless=False) as (page, context):
            self.logger.info("TIMETREE_NAVIGATE operation=login url=%s", self.config.sign_in_url)
            page.goto(self.config.sign_in_url, wait_until="domcontentloaded")
            self._install_login_diagnostics(context)
            authenticated_page = self._wait_for_authenticated_page(
                context,
                page,
                wait_seconds=wait_seconds,
            )
            if authenticated_page is None:
                raise AuthenticationRequired(
                    "Manual login did not complete before the timeout. CAPTCHA and 2FA must be completed by a human."
                )
            self._save_storage_state(context)
            self._save_auth_metadata(authenticated_page.url)
            self.logger.info(
                "TIMETREE_AUTH_OK operation=login url=%s state=%s",
                authenticated_page.url,
                self.config.storage_state_path,
            )
            return self.config.storage_state_path

    def check_auth(self) -> dict[str, Any]:
        state_exists = self.config.storage_state_path.exists()
        with self._session("status") as (page, _):
            self._navigate(page, self._authenticated_entry_url(), "status")
            required = self._auth_required(page)
            if required:
                self.logger.warning(
                    "TIMETREE_AUTH_REQUIRED state_exists=%s url=%s",
                    state_exists,
                    page.url,
                )
            else:
                self.logger.info("TIMETREE_AUTH_OK url=%s", page.url)
                self._save_auth_metadata(page.url)
            return {
                "authenticated": not required,
                "storage_state_exists": state_exists,
                "storage_state": str(self.config.storage_state_path),
                "url": page.url,
            }

    def list_calendars(self) -> list[CalendarInfo]:
        with self._session("calendars") as (page, _):
            self._open_authenticated_home(page)
            if self.config.calendar_name:
                calendars = self._discover_calendar_candidates(
                    page,
                    self.config.calendar_name,
                )
                resolved = self._resolve_calendar_candidates(
                    page,
                    self.config.calendar_name,
                    calendars,
                )
                calendars = [
                    resolved if calendar.name == resolved.name else calendar
                    for calendar in calendars
                ]
                self.logger.info(
                    "TIMETREE_CALENDAR_FOUND name=%s url=%s",
                    resolved.name,
                    resolved.url,
                )
            else:
                calendars = self._calendar_links(page, expand=True)
            return calendars

    def probe(
        self,
        *,
        surface: str = "home",
        record_id: str | None = None,
        event_date: date | None = None,
    ) -> dict[str, Any]:
        form_state: dict[str, Any] | None = None
        with self._session("probe") as (page, _):
            self._open_authenticated_home(page)
            if surface in ("create", "create-filled"):
                calendar = self._resolve_calendar(page, self._require_calendar_name())
                self._open_calendar(page, calendar)
                self._open_create_form(page)
                if surface == "create-filled":
                    if event_date is None:
                        raise ValueError("--date is required for probe --surface create-filled")
                    spec = build_test_event(event_date)
                    form_state = self._prepare_event_form(page, spec)
            elif surface == "owned":
                self._open_owned_event(page, self.registry.get(record_id))
            elif surface != "home":
                raise ValueError(f"Unsupported probe surface: {surface}")
            self._log_page_diagnostics(page, "probe_before_capture")
            slug = timestamp_slug()
            destination = self.config.artifacts_dir / f"{slug}_probe_{surface}"
            destination.mkdir(parents=True, exist_ok=True)
            destination.chmod(0o700)
            screenshot_path = destination / "page.png"
            elements_path = destination / "interactive-elements.json"
            page.screenshot(path=str(screenshot_path), full_page=True)
            screenshot_path.chmod(0o600)
            elements = page.locator(
                "a,button,input,textarea,select,[role],[aria-label],[data-testid],[data-test-id]"
            ).evaluate_all(
                """
                elements => elements.map((element) => ({
                  tag: element.tagName.toLowerCase(),
                  role: element.getAttribute('role'),
                  ariaLabel: element.getAttribute('aria-label'),
                  dataTestId: element.getAttribute('data-testid') || element.getAttribute('data-test-id'),
                  name: element.getAttribute('name'),
                  type: element.getAttribute('type'),
                  placeholder: element.getAttribute('placeholder'),
                  href: element.getAttribute('href'),
                  visible: Boolean(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
                  disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
                  text: (element.innerText || '').trim().slice(0, 300),
                }))
                """
            )
            write_private_json(
                elements_path,
                {"url": page.url, "captured_at": slug, "surface": surface, "elements": elements},
            )
            result = {
                "screenshot": str(screenshot_path),
                "interactive_elements": str(elements_path),
            }
            if self.config.debug:
                html_path = destination / "page.html"
                html_path.write_text(page.content(), encoding="utf-8")
                html_path.chmod(0o600)
                result["html"] = str(html_path)
            if form_state is not None:
                result["form_state"] = form_state
            self._log_page_diagnostics(page, "probe_after_capture")
            self.logger.info("TIMETREE_PROBE_SAVED paths=%s", result)
            return result

    def create_event(
        self,
        *,
        event_date: date,
        title: str | None = None,
        dry_run: bool = True,
    ) -> OwnedEventRecord | dict[str, Any]:
        calendar_name = self._require_calendar_name()
        spec = build_test_event(event_date, title)
        with self._session("create_test") as (page, _):
            self._open_authenticated_home(page)
            calendar = self._resolve_calendar(page, calendar_name)
            if dry_run:
                plan = {
                    "dry_run": True,
                    "operation": "create",
                    "calendar": calendar.name,
                    "calendar_url": calendar.url,
                    "date": event_date.isoformat(),
                    "title": spec.title,
                }
                self.logger.info("TIMETREE_DRY_RUN plan=%s", plan)
                return plan
            self._open_calendar(page, calendar)
            self._open_create_form(page)
            self._prepare_event_form(page, spec)
            self._save_prepared_event(page, spec, calendar_name)
            page.wait_for_timeout(1000)
            event_url = self._resolve_created_event_url(page, spec)
            visible_text = page.locator("body").inner_text()
            event_id = derive_event_id(event_url)
            if not event_id or spec.title not in visible_text or spec.ownership_token not in visible_text:
                raise OwnershipError(
                    "Creation could not be tied to a stable event URL and the exact ownership token; refusing to record success."
                )
            record = self.registry.add(
                spec=spec,
                calendar_name=calendar_name,
                event_url=event_url,
            )
            self.registry.clear_pending_create(spec.ownership_token)
            self.logger.info(
                "TIMETREE_EVENT_CREATED record_id=%s event_id=%s title=%s",
                record.record_id,
                record.event_id,
                record.current_title,
            )
            return record

    def update_event(
        self,
        *,
        record_id: str | None = None,
        title: str | None = None,
        dry_run: bool = True,
    ) -> OwnedEventRecord | dict[str, Any]:
        record = self.registry.get(record_id)
        updated_title = build_updated_title(record, title)
        with self._session("update_test") as (page, _):
            self._open_owned_event(page, record)
            if dry_run:
                plan = {
                    "dry_run": True,
                    "operation": "update",
                    "record_id": record.record_id,
                    "event_id": record.event_id,
                    "from": record.current_title,
                    "to": updated_title,
                }
                self.logger.info("TIMETREE_DRY_RUN plan=%s", plan)
                return plan
            self._open_event_action(page, EDIT_NAMES, "edit")
            title_field = self._wait_for_event_title_field(
                page,
                expected_value=record.current_title,
                action="edit form",
            )
            title_field.fill(updated_title)
            if title_field.input_value() != updated_title:
                raise EventFormInvalid(
                    "The edit form title did not retain the exact safe updated title; refusing to Save."
                )
            click_role(page, "button", SAVE_NAMES, "save button")
            page.wait_for_timeout(1000)
            self._verify_event_after_update(page, record, updated_title)
            record = self.registry.update_title(record.record_id, updated_title)
            self.logger.info(
                "TIMETREE_EVENT_UPDATED record_id=%s event_id=%s title=%s",
                record.record_id,
                record.event_id,
                record.current_title,
            )
            return record

    def delete_event(
        self,
        *,
        record_id: str | None = None,
        dry_run: bool = True,
    ) -> OwnedEventRecord | dict[str, Any]:
        record = self.registry.get(record_id)
        with self._session("delete_test") as (page, _):
            self._open_owned_event(page, record)
            if dry_run:
                plan = {
                    "dry_run": True,
                    "operation": "delete",
                    "record_id": record.record_id,
                    "event_id": record.event_id,
                    "title": record.current_title,
                    "url": record.event_url,
                }
                self.logger.info("TIMETREE_DRY_RUN plan=%s", plan)
                return plan
            self._open_event_action(page, DELETE_NAMES, "delete")
            click_role(page, "button", CONFIRM_DELETE_NAMES, "delete confirmation button")
            page.wait_for_timeout(1000)
            self._verify_event_deleted(page, record)
            record = self.registry.mark_deleted(record.record_id)
            self.logger.info(
                "TIMETREE_EVENT_DELETED record_id=%s event_id=%s",
                record.record_id,
                record.event_id,
            )
            return record

    def cleanup_events(self, *, dry_run: bool = True, limit: int = 10) -> list[Any]:
        if limit < 1 or limit > 20:
            raise ValueError("cleanup limit must be between 1 and 20")
        records = self.registry.list(active_only=True)[:limit]
        return [self.delete_event(record_id=record.record_id, dry_run=dry_run) for record in records]

    def _open_authenticated_home(self, page: Page) -> None:
        self._navigate(page, self._authenticated_entry_url(), "home")
        if self._auth_required(page):
            self.logger.warning("TIMETREE_AUTH_REQUIRED url=%s", page.url)
            raise AuthenticationRequired(
                "TimeTree authentication is required or expired. Run the manual login flow again."
            )
        self.logger.info("TIMETREE_AUTH_OK url=%s", page.url)
        self._save_auth_metadata(page.url)

    def _navigate(self, page: Page, url: str, operation: str) -> None:
        self.logger.info("TIMETREE_NAVIGATE operation=%s url=%s", operation, url)
        page.goto(url, wait_until="domcontentloaded")
        if self._is_authenticated_app_route(page.url):
            self._wait_for_app_shell(page, operation)

    @staticmethod
    def _is_authenticated_app_route(url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in ("/calendars", "/calendar", "/home", "/activity", "/events", "/settings")
        )

    def _wait_for_app_shell(self, page: Page, operation: str) -> None:
        self._log_page_diagnostics(page, f"{operation}_spa_before")
        try:
            page.wait_for_function(
                """
                () => {
                  const root = document.querySelector('#react-root');
                  if (!root || document.readyState === 'loading') return false;
                  const loading = root.querySelector('.loading');
                  const loadingVisible = loading &&
                    (loading.offsetWidth || loading.offsetHeight || loading.getClientRects().length);
                  const interactive = root.querySelector(
                    'a,button,input,textarea,select,[role],[aria-label],[data-testid],[data-test-id]'
                  );
                  const authenticatedShellControls = root.querySelectorAll(
                    'button[aria-label="Expand"],button[aria-label="Create an event"],a[href="/calendars"]'
                  );
                  const shellControlVisible = Array.from(authenticatedShellControls).some(
                    element => element.offsetWidth || element.offsetHeight || element.getClientRects().length
                  );
                  return !loadingVisible && Boolean(interactive) && shellControlVisible;
                }
                """,
                timeout=self.config.timeout_ms,
                polling=100,
            )
        except PlaywrightTimeoutError as exc:
            self._log_page_diagnostics(page, f"{operation}_spa_timeout")
            raise RuntimeError(
                "TimeTree SPA did not render an interactive authenticated application shell "
                f"within {self.config.timeout_ms}ms."
            ) from exc
        self._log_page_diagnostics(page, f"{operation}_spa_ready")

    def _page_diagnostics(self, page: Page) -> dict[str, Any]:
        values = page.evaluate(
            """
            () => ({
              readyState: document.readyState,
              interactiveElementCount: document.querySelectorAll(
                'a,button,input,textarea,select,[role],[aria-label],[data-testid],[data-test-id]'
              ).length,
              bodyTextLength: (document.body?.innerText || '').length,
              calendarLinkCandidateCount: document.querySelectorAll("a[href*='/calendars/']").length,
            })
            """
        )
        raw_title = page.title().replace("\r", " ").replace("\n", " ")[:200]
        title = "TimeTree" if "TimeTree" in raw_title else "[redacted]"
        return {
            "ready_state": values.get("readyState"),
            "url": self._safe_log_url(page),
            "interactive_element_count": int(values.get("interactiveElementCount", 0)),
            "body_text_length": int(values.get("bodyTextLength", 0)),
            "calendar_link_candidate_count": int(values.get("calendarLinkCandidateCount", 0)),
            "page_title": title,
        }

    def _log_page_diagnostics(self, page: Page, phase: str) -> None:
        if not self.config.debug:
            return
        try:
            diagnostics = self._page_diagnostics(page)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not mask the operation
            self.logger.warning(
                "TIMETREE_PAGE_DIAGNOSTICS phase=%s unavailable=%s",
                phase,
                type(exc).__name__,
            )
            return
        self.logger.info(
            "TIMETREE_PAGE_DIAGNOSTICS phase=%s values=%s",
            phase,
            diagnostics,
        )

    def _auth_required(self, page: Page) -> bool:
        return self._assess_auth(page).required

    def _assess_auth(self, page: Page) -> AuthAssessment:
        try:
            if page.is_closed():
                return AuthAssessment(required=True, reason="page_closed")
            current_url = page.url
        except Exception:  # noqa: BLE001 - authentication checks must fail closed
            return AuthAssessment(required=True, reason="page_unavailable")
        path = urlparse(current_url).path.lower()
        if not self._is_timetree_url(current_url):
            return AuthAssessment(required=True, reason="non_timetree_url")
        if path.startswith(("/signin", "/signup", "/forgot", "/intl/")):
            return AuthAssessment(required=True, reason="public_route")
        email_field = first_visible(
            (
                page.get_by_label("Email Address", exact=True),
                page.get_by_role("textbox", name="Email Address", exact=True),
                page.locator("input[type='email']"),
            )
        )
        if email_field is not None:
            return AuthAssessment(required=True, reason="email_login_field")
        sign_in = first_visible(
            page.get_by_role(role, name=name, exact=True)
            for role in ("link", "button")
            for name in ("Sign in", "Log in", "ログイン", "サインイン")
        )
        if sign_in is not None:
            return AuthAssessment(required=True, reason="sign_in_control")

        # Authentication is deliberately fail-closed. A missing login form is
        # not enough: public marketing pages also have no form. Require a route
        # or link that belongs to the signed-in calendar application.
        app_route = self._is_authenticated_app_route(current_url)
        if app_route:
            return AuthAssessment(required=False, reason="authenticated_app_route")
        try:
            if page.locator("a[href*='/calendars/']").count() > 0:
                return AuthAssessment(required=False, reason="authenticated_calendar_link")
        except Exception:  # noqa: BLE001,S110 - authentication checks must fail closed
            pass
        return AuthAssessment(required=True, reason="no_authenticated_evidence")

    def _wait_for_authenticated_page(
        self,
        context: BrowserContext,
        initial_page: Page,
        *,
        wait_seconds: int,
    ) -> Page | None:
        deadline = time.monotonic() + wait_seconds
        last_snapshot: tuple[tuple[str, bool, str], ...] | None = None
        while time.monotonic() < deadline:
            snapshot: list[tuple[str, bool, str]] = []
            authenticated_page: Page | None = None
            live_pages: list[Page] = []
            for candidate in reversed(context.pages):
                assessment = self._assess_auth(candidate)
                candidate_url = self._safe_log_url(candidate)
                snapshot.append((candidate_url, assessment.required, assessment.reason))
                try:
                    if not candidate.is_closed():
                        live_pages.append(candidate)
                except Exception:  # noqa: BLE001 - a closing page is not usable
                    pass
                if not assessment.required and self._is_timetree_url(candidate_url):
                    authenticated_page = candidate
                    break
            current_snapshot = tuple(snapshot)
            if self.config.debug and current_snapshot != last_snapshot:
                self.logger.info(
                    "TIMETREE_AUTH_PROBE page_count=%s pages=%s",
                    len(context.pages),
                    [
                        {"url": url, "auth_required": required, "reason": reason}
                        for url, required, reason in current_snapshot
                    ],
                )
                last_snapshot = current_snapshot
            if authenticated_page is not None:
                return authenticated_page
            if not live_pages:
                return None

            # Playwright's synchronous API dispatches browser events while a
            # Playwright call is running. time.sleep() blocks that dispatcher,
            # leaving context.pages and Page.url stale after a human login.
            pump_page = live_pages[0]
            try:
                pump_page.wait_for_timeout(250)
            except Exception:  # noqa: BLE001 - page may close while a new login tab opens
                try:
                    if not initial_page.is_closed():
                        initial_page.wait_for_timeout(250)
                except Exception:  # noqa: BLE001 - next iteration fails closed if all pages closed
                    pass
        return None

    def _install_login_diagnostics(self, context: BrowserContext) -> None:
        if not self.config.debug:
            return
        attached: set[int] = set()

        def attach(observed_page: Page) -> None:
            identity = id(observed_page)
            if identity in attached:
                return
            attached.add(identity)
            self.logger.info(
                "TIMETREE_PAGE_OPEN page_count=%s url=%s",
                len(context.pages),
                self._safe_log_url(observed_page),
            )
            observed_page.on(
                "framenavigated",
                lambda frame: self.logger.info(
                    "TIMETREE_PAGE_NAVIGATE page_count=%s url=%s",
                    len(context.pages),
                    self._safe_log_url(observed_page),
                )
                if frame == observed_page.main_frame
                else None,
            )
            observed_page.on(
                "close",
                lambda: self.logger.info(
                    "TIMETREE_PAGE_CLOSE page_count=%s url=%s",
                    len(context.pages),
                    self._safe_log_url(observed_page),
                ),
            )

        for existing_page in context.pages:
            attach(existing_page)
        context.on("page", attach)

    @staticmethod
    def _safe_log_url(page: Page) -> str:
        try:
            parsed = urlparse(page.url)
            if parsed.scheme not in ("http", "https"):
                return f"{parsed.scheme}:" if parsed.scheme else "unavailable"
            return parsed._replace(query="", fragment="").geturl()
        except Exception:  # noqa: BLE001 - diagnostics must not mask the original operation
            return "unavailable"

    def _save_storage_state(self, context: BrowserContext) -> None:
        context.storage_state(path=str(self.config.storage_state_path))
        self.config.storage_state_path.chmod(0o600)

    def _save_auth_metadata(self, url: str) -> None:
        if not self._is_timetree_url(url) or self._is_public_route(url):
            return
        write_private_json(
            self.config.auth_metadata_path,
            {
                "version": 1,
                "authenticated_entry_url": url,
                "updated_at": utc_now_iso(),
            },
        )

    def _authenticated_entry_url(self) -> str:
        if not self.config.auth_metadata_path.exists():
            return self.config.base_url
        try:
            payload = json.loads(self.config.auth_metadata_path.read_text(encoding="utf-8"))
            url = str(payload.get("authenticated_entry_url", ""))
            if payload.get("version") == 1 and self._is_timetree_url(url) and not self._is_public_route(url):
                return url
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.logger.warning(
                "TIMETREE_AUTH_METADATA_INVALID path=%s",
                self.config.auth_metadata_path,
            )
        return self.config.base_url

    @staticmethod
    def _is_timetree_url(url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "timetreeapp.com"
            and parsed.netloc == "timetreeapp.com"
            and not parsed.username
            and not parsed.password
        )

    @staticmethod
    def _is_public_route(url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.startswith(("/signin", "/signup", "/forgot", "/intl/"))

    def _calendar_links(self, page: Page, *, expand: bool) -> list[CalendarInfo]:
        self._log_calendar_debug(page, "discovery_start")
        self._log_page_diagnostics(page, "calendar_links_before")
        calendars = self._read_calendar_links(page)
        if calendars or not expand:
            self._log_calendar_debug(page, "discovery_complete")
            return calendars
        control = role_locator(page, "button", CALENDAR_LIST_NAMES) or role_locator(
            page, "link", CALENDAR_LIST_NAMES
        )
        if control is not None:
            self._log_calendar_debug(page, "expand_click_before")
            control.click()
            try:
                page.wait_for_function(
                    """
                    () => document.querySelectorAll("a[href*='/calendars/']").length > 0 ||
                      document.querySelectorAll('button[aria-label="Show only this calendar"]').length > 0
                    """,
                    timeout=self.config.timeout_ms,
                    polling=100,
                )
            except PlaywrightTimeoutError:
                self.logger.warning(
                    "TIMETREE_CALENDAR_LIST_WAIT_TIMEOUT timeout_ms=%s",
                    self.config.timeout_ms,
                )
            calendars = self._read_calendar_links(page)
            self._log_calendar_debug(page, "expand_click_after")
            self._log_page_diagnostics(page, "calendar_links_after_expand")
        self._log_calendar_debug(page, "discovery_complete")
        return calendars

    def _read_calendar_links(self, page: Page) -> list[CalendarInfo]:
        values = page.locator("a[href*='/calendars/']").evaluate_all(
            """
            links => links.map(link => ({
              name: (link.innerText || link.getAttribute('aria-label') || '').trim(),
              url: link.href,
            })).filter(item => item.name && item.url)
            """
        )
        found: dict[tuple[str, str], CalendarInfo] = {}
        for value in values:
            name = str(value["name"]).strip()
            url = str(value["url"])
            if derive_event_id(url):
                continue
            found[(name, url)] = CalendarInfo(name=name, url=url)
        if found:
            return list(found.values())

        # The authenticated TimeTree UI observed on 2026-09-27 renders the
        # Calendar List as semantic list rows rather than navigation links.
        # Each row has one h2 name and a button named "Show only this calendar".
        show_only = page.get_by_role(
            "button",
            name=SHOW_ONLY_CALENDAR_NAMES[0],
            exact=True,
        )
        rows = page.locator("li").filter(has=show_only)
        calendars: list[CalendarInfo] = []
        for index in range(rows.count()):
            row = rows.nth(index)
            if not row.is_visible():
                continue
            headings = row.get_by_role("heading", level=2)
            visible_headings = [
                headings.nth(heading_index)
                for heading_index in range(headings.count())
                if headings.nth(heading_index).is_visible()
            ]
            if len(visible_headings) != 1:
                self.logger.warning(
                    "TIMETREE_CALENDAR_ROW_SKIPPED reason=heading_count count=%s",
                    len(visible_headings),
                )
                continue
            name = visible_headings[0].inner_text().strip()
            if name:
                calendars.append(
                    CalendarInfo(
                        name=name,
                        url=self._current_calendar_url(page, name) or "",
                    )
                )
        return calendars

    def _resolve_calendar(self, page: Page, name: str) -> CalendarInfo:
        calendars = self._discover_calendar_candidates(page, name)
        return self._resolve_calendar_candidates(page, name, calendars)

    def _discover_calendar_candidates(self, page: Page, name: str) -> list[CalendarInfo]:
        calendars = self._calendar_links(page, expand=True)
        if any(calendar.name == name for calendar in calendars):
            return calendars

        self._log_calendar_debug(page, "target_wait_start", calendar_name=name)
        try:
            page.wait_for_function(
                """
                ({ expectedName, showOnlyName }) => {
                  const visible = element => Boolean(
                    element.offsetWidth || element.offsetHeight || element.getClientRects().length
                  );
                  const canonicalCalendarLink = Array.from(
                    document.querySelectorAll("a[href*='/calendars/']")
                  ).some(link => {
                    if (!visible(link)) return false;
                    const linkName = (link.innerText || link.getAttribute('aria-label') || '').trim();
                    let pathParts;
                    try {
                      pathParts = new URL(link.href, location.href).pathname.split('/').filter(Boolean);
                    } catch (_) {
                      return false;
                    }
                    return linkName === expectedName && pathParts.length === 2 &&
                      pathParts[0] === 'calendars' && Boolean(pathParts[1]);
                  });
                  const semanticCalendarRow = Array.from(document.querySelectorAll('li')).some(row => {
                    if (!visible(row)) return false;
                    const dedicatedControl = Array.from(row.querySelectorAll('button')).some(
                      control => control.getAttribute('aria-label') === showOnlyName
                    );
                    if (!dedicatedControl) return false;
                    const headings = Array.from(row.querySelectorAll('h2')).filter(visible);
                    return headings.length === 1 && headings[0].innerText.trim() === expectedName;
                  });
                  return canonicalCalendarLink || semanticCalendarRow;
                }
                """,
                arg={
                    "expectedName": name,
                    "showOnlyName": SHOW_ONLY_CALENDAR_NAMES[0],
                },
                timeout=self.config.timeout_ms,
                polling=100,
            )
        except PlaywrightTimeoutError:
            self.logger.warning(
                "TIMETREE_CALENDAR_TARGET_WAIT_TIMEOUT timeout_ms=%s",
                self.config.timeout_ms,
            )
        calendars = self._read_calendar_links(page)
        self._log_calendar_debug(page, "target_wait_complete", calendar_name=name)
        return calendars

    def _resolve_calendar_candidates(
        self,
        page: Page,
        name: str,
        calendars: list[CalendarInfo],
    ) -> CalendarInfo:
        for candidate in calendars:
            self._log_calendar_debug(
                page,
                "discovery_candidate",
                calendar_name=candidate.name,
                calendar_url=candidate.url,
            )
        matches = [calendar for calendar in calendars if calendar.name == name]
        if len(matches) != 1:
            available = [calendar.name for calendar in calendars]
            raise CalendarNotFound(
                f"Expected exactly one calendar named {name!r}; found {len(matches)}. Available link names: {available}"
            )
        calendar = matches[0]
        if not calendar.url and self._calendar_page_url(page) is not None:
            # The calendar rows can render before React updates document.title.
            # Wait for the current route's identity instead of using debug-log
            # latency or clicking a heading that navigates back to /calendars.
            self._wait_for_calendar_identity(page, calendar.name)
            current_url = self._current_calendar_url(page, calendar.name)
            if current_url is None:
                raise CalendarNotFound(
                    f"Calendar {calendar.name!r} could not be tied to the current calendar URL."
                )
            calendar = CalendarInfo(name=calendar.name, url=current_url)
        self._log_calendar_debug(
            page,
            "resolved",
            calendar_name=calendar.name,
            calendar_url=calendar.url,
        )
        self.logger.info("TIMETREE_CALENDAR_FOUND name=%s url=%s", calendar.name, calendar.url)
        return calendar

    def _open_calendar(self, page: Page, calendar: CalendarInfo) -> None:
        self._log_calendar_debug(
            page,
            "open_start",
            calendar_name=calendar.name,
            calendar_url=calendar.url,
        )
        current_url = self._current_calendar_url(page, calendar.name)
        if current_url is not None:
            self.logger.info(
                "TIMETREE_CALENDAR_ALREADY_OPEN name=%s url=%s reason=exact_title_and_canonical_url",
                calendar.name,
                current_url,
            )
            return
        if calendar.url:
            self._log_calendar_debug(
                page,
                "navigate_before",
                calendar_name=calendar.name,
                calendar_url=calendar.url,
            )
            self._navigate(page, calendar.url, "open_calendar")
            self._log_calendar_debug(
                page,
                "navigate_after",
                calendar_name=calendar.name,
                calendar_url=calendar.url,
            )
        else:
            raise CalendarNotFound(
                f"Calendar {calendar.name!r} has no verified URL and is not the uniquely "
                "identified current calendar; refusing to click or navigate."
            )
        self._wait_for_calendar_identity(page, calendar.name)

    def _page_shows_calendar(self, page: Page, calendar_name: str) -> bool:
        try:
            return (
                self._calendar_page_url(page) is not None
                and page.title() == f"{calendar_name} - TimeTree"
            )
        except Exception:  # noqa: BLE001 - calendar identity must fail closed
            return False

    def _current_calendar_url(self, page: Page, calendar_name: str) -> str | None:
        if not self._page_shows_calendar(page, calendar_name):
            return None
        return self._calendar_page_url(page)

    def _calendar_page_url(self, page: Page) -> str | None:
        if not self._is_timetree_url(page.url):
            return None
        parsed = urlparse(page.url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0].lower() != "calendars" or not parts[1]:
            return None
        return parsed._replace(query="", fragment="").geturl()

    def _wait_for_calendar_identity(self, page: Page, calendar_name: str) -> None:
        self._log_calendar_debug(
            page,
            "identity_wait_start",
            calendar_name=calendar_name,
        )
        if self._calendar_page_url(page) is None:
            raise CalendarNotFound(
                f"Calendar {calendar_name!r} cannot be identified outside a canonical calendar URL."
            )
        try:
            current_title = page.title()
        except Exception as exc:  # noqa: BLE001 - identity checks must fail closed
            raise CalendarNotFound(
                f"Calendar {calendar_name!r} title could not be read."
            ) from exc
        expected_title = f"{calendar_name} - TimeTree"
        identity_expression = """
            expectedName => {
              const parts = location.pathname.split('/').filter(Boolean);
              return document.title === `${expectedName} - TimeTree` &&
                parts.length === 2 && parts[0] === 'calendars' && Boolean(parts[1]);
            }
        """
        if current_title not in ("", "TimeTree", expected_title):
            # A newly loaded TimeTree SPA can briefly expose a stale/generic
            # title even though the canonical route is already correct. Allow
            # only a short identity-only wait. No click or navigation occurs.
            try:
                page.wait_for_function(
                    identity_expression,
                    arg=calendar_name,
                    timeout=min(self.config.timeout_ms, 3_000),
                    polling=100,
                )
            except PlaywrightTimeoutError as exc:
                raise CalendarNotFound(
                    f"Current calendar does not match {calendar_name!r}; refusing to navigate or click."
                ) from exc
        try:
            page.wait_for_function(
                identity_expression,
                arg=calendar_name,
                timeout=self.config.timeout_ms,
                polling=100,
            )
        except PlaywrightTimeoutError as exc:
            raise CalendarNotFound(
                f"Calendar {calendar_name!r} did not become the uniquely identified current calendar."
            ) from exc
        self._log_calendar_debug(
            page,
            "identity_confirmed",
            calendar_name=calendar_name,
            calendar_url=self._current_calendar_url(page, calendar_name),
        )

    def _log_calendar_debug(
        self,
        page: Page,
        phase: str,
        *,
        calendar_name: str | None = None,
        calendar_url: str | None = None,
    ) -> None:
        if not self.config.debug:
            return
        self.logger.info(
            "TIMETREE_CALENDAR_DEBUG phase=%s current_url=%s calendar_name=%s calendar_url=%s",
            phase,
            self._safe_log_url(page),
            calendar_name or "",
            calendar_url or "",
        )

    def _open_create_form(self, page: Page) -> None:
        control = unique_role_locator(page, "button", CREATE_EVENT_NAMES, "open create-event form")
        if control is None:
            control = unique_role_locator(page, "link", CREATE_EVENT_NAMES, "open create-event form")
        if control is None:
            raise SelectorNotFound(
                f"Could not find create-event control by accessible name: {CREATE_EVENT_NAMES}"
            )
        control.click()
        self._wait_for_event_title_field(
            page,
            expected_value=None,
            action="create form",
        )

    def _wait_for_event_title_field(
        self,
        page: Page,
        *,
        expected_value: str | None,
        action: str,
    ) -> Any:
        try:
            page.wait_for_function(
                """
                ({ selector, expectedValue }) => {
                  const visible = element => Boolean(
                    element.offsetWidth || element.offsetHeight || element.getClientRects().length
                  );
                  const fields = Array.from(document.querySelectorAll(selector)).filter(visible);
                  return fields.length === 1 &&
                    (expectedValue === null || fields[0].value === expectedValue);
                }
                """,
                arg={
                    "selector": EVENT_TITLE_FIELD_SELECTOR,
                    "expectedValue": expected_value,
                },
                timeout=self.config.timeout_ms,
                polling=100,
            )
        except PlaywrightTimeoutError as exc:
            raise SelectorNotFound(
                f"The {action} title field did not become uniquely visible with the expected value."
            ) from exc
        title_field = page.locator(EVENT_TITLE_FIELD_SELECTOR)
        field = unique_visible((title_field,), f"verify {action} title field")
        if field is None:
            raise SelectorNotFound(f"The {action} title field is not visible.")
        if expected_value is not None and field.input_value() != expected_value:
            raise SelectorNotFound(
                f"The {action} title field does not contain the exact stored title."
            )
        return field

    def _fill_event_form(self, page: Page, spec: TestEventSpec) -> None:
        if not self._fill_title(page, spec.title):
            raise SelectorNotFound("Could not find the event title field by label or stable input attribute.")
        date_value = self._format_timetree_date(spec.event_date)
        self._set_all_day(page, enabled=False)
        self._fill_observed_input(
            page,
            "input[name='dateTime.startDate'][data-test-id='start-date-picker']",
            date_value,
            "start date",
        )
        self._fill_observed_input(
            page,
            "input[name='dateTime.startTime'][data-test-id='start-time-picker']",
            "7:00 PM",
            "start time",
        )
        self._fill_observed_input(
            page,
            "input[name='dateTime.endDate'][data-test-id='end-date-picker']",
            date_value,
            "end date",
        )
        self._fill_observed_input(
            page,
            "input[name='dateTime.endTime'][data-test-id='end-time-picker']",
            "8:00 PM",
            "end time",
        )
        if not fill_labeled(page, DESCRIPTION_LABELS, spec.description, "description"):
            description = unique_visible(
                (
                    page.locator(
                        "textarea[placeholder='Add event details up to 10,000 characters']"
                    ),
                ),
                "fill event description",
            )
            if description is None:
                note = unique_role_locator(page, "button", NOTE_NAMES, "open event note")
                if note is not None:
                    note.click()
                    observed_description = page.locator(
                        "textarea[placeholder='Add event details up to 10,000 characters']"
                    )
                    try:
                        observed_description.first.wait_for(
                            state="visible",
                            timeout=self.config.timeout_ms,
                        )
                    except PlaywrightTimeoutError:
                        observed_description = page.locator(
                            "textarea[placeholder='Add event details up to 10,000 characters']"
                        )
                    description = unique_visible(
                        (observed_description,),
                        "fill event description",
                    )
            if description is not None:
                description.fill(spec.description)
                confirm = unique_role_locator(
                    page,
                    "button",
                    NOTE_CONFIRM_NAMES,
                    "confirm event note",
                )
                if confirm is None:
                    raise EventFormInvalid(
                        "The event note dialog has no unique confirmation control; refusing to continue."
                    )
                confirm.click()
                try:
                    description.wait_for(state="hidden", timeout=self.config.timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise EventFormInvalid(
                        "The event note dialog did not close after confirmation."
                    ) from exc
            else:
                self.logger.warning(
                    "TIMETREE_SELECTOR_OPTIONAL_MISSING field=description token_remains_in_title=true"
                )

    def _prepare_event_form(
        self,
        page: Page,
        spec: TestEventSpec,
    ) -> dict[str, Any]:
        self._fill_event_form(page, spec)
        try:
            page.wait_for_function(
                """
                () => {
                  const save = document.querySelector(
                    "button[data-test-id='event-form-submit-button']"
                  );
                  return Boolean(save) && !save.disabled &&
                    save.getAttribute('aria-disabled') !== 'true';
                }
                """,
                timeout=min(self.config.timeout_ms, 5_000),
                polling=100,
            )
        except PlaywrightTimeoutError:
            # Validation below captures every observed field and raises the
            # dedicated fail-closed error. Never click a disabled Save button.
            pass
        return self._validate_event_form(page, spec)

    def _set_all_day(self, page: Page, *, enabled: bool) -> None:
        switch = unique_visible(
            (
                page.locator(
                    "button[role='switch'][data-test-id='allday-checkbox']"
                ),
            ),
            "set all-day state",
        )
        if switch is None:
            raise SelectorNotFound("Could not find the observed all-day switch.")
        current = switch.get_attribute("aria-checked") == "true"
        if current != enabled:
            switch.click()
            try:
                switch.wait_for(
                    state="visible",
                    timeout=self.config.timeout_ms,
                )
                page.wait_for_function(
                    """
                    expected => document.querySelector(
                      "button[role='switch'][data-test-id='allday-checkbox']"
                    )?.getAttribute('aria-checked') === String(expected)
                    """,
                    arg=str(enabled).lower(),
                    timeout=self.config.timeout_ms,
                    polling=100,
                )
            except PlaywrightTimeoutError as exc:
                raise EventFormInvalid("All-day state did not update.") from exc

    def _fill_observed_input(
        self,
        page: Page,
        selector: str,
        value: str,
        field_name: str,
    ) -> None:
        control = unique_visible((page.locator(selector),), f"fill {field_name}")
        if control is None:
            raise SelectorNotFound(f"Could not find the observed {field_name} input.")
        control.fill(value)
        control.press("Tab")

    @staticmethod
    def _format_timetree_date(value: date) -> str:
        weekdays = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        months = (
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        )
        return f"{weekdays[value.weekday()]}, {months[value.month - 1]} {value.day}, {value.year}"

    @staticmethod
    def _parse_timetree_date(value: str) -> str | None:
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            pass
        try:
            parsed = time.strptime(value, "%a, %b %d, %Y")
            return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}"
        except ValueError:
            return None

    def _save_event_control(self, page: Page) -> Any:
        save = unique_visible(
            (page.locator("button[data-test-id='event-form-submit-button']"),),
            "save/create button",
        )
        if save is None:
            raise SelectorNotFound("Could not find the observed event form Save button.")
        return save

    def _save_prepared_event(
        self,
        page: Page,
        spec: TestEventSpec,
        calendar_name: str,
    ) -> None:
        save_control = self._save_event_control(page)
        if not save_control.is_enabled():
            raise EventFormInvalid("Event form became disabled after validation; refusing to save.")
        # Record the ownership token only once the form is valid and immediately
        # before the single external write attempt. A click failure intentionally
        # leaves this record for safe human reconciliation.
        self.registry.record_pending_create(spec=spec, calendar_name=calendar_name)
        save_control.click()

    def _event_form_state(self, page: Page) -> dict[str, Any]:
        def input_state(selector: str, field_name: str) -> dict[str, Any]:
            control = unique_visible((page.locator(selector),), f"inspect {field_name}")
            if control is None:
                raise EventFormInvalid(f"The {field_name} input is not uniquely visible.")
            value = control.input_value()
            result = {
                "value": value,
                "aria_invalid": control.get_attribute("aria-invalid"),
                "disabled": control.is_disabled(),
            }
            if field_name in ("start date", "end date"):
                result["date"] = self._parse_timetree_date(value)
            return result

        all_day = unique_visible(
            (
                page.locator(
                    "button[role='switch'][data-test-id='allday-checkbox']"
                ),
            ),
            "inspect all-day state",
        )
        if all_day is None:
            raise EventFormInvalid("The all-day switch is not uniquely visible.")
        save = self._save_event_control(page)
        validation_messages = page.locator(
            "[data-test-id='event-form'] [role='alert'], "
            "[data-test-id='event-form'] [aria-live='assertive']"
        ).all_inner_texts()
        state = {
            "url": self._safe_log_url(page),
            "title": input_state(
                EVENT_TITLE_FIELD_SELECTOR,
                "title",
            ),
            "start_date": input_state(
                "input[name='dateTime.startDate'][data-test-id='start-date-picker']",
                "start date",
            ),
            "start_time": input_state(
                "input[name='dateTime.startTime'][data-test-id='start-time-picker']",
                "start time",
            ),
            "end_date": input_state(
                "input[name='dateTime.endDate'][data-test-id='end-date-picker']",
                "end date",
            ),
            "end_time": input_state(
                "input[name='dateTime.endTime'][data-test-id='end-time-picker']",
                "end time",
            ),
            "all_day": {
                "checked": all_day.get_attribute("aria-checked") == "true",
                "aria_invalid": all_day.get_attribute("aria-invalid"),
                "disabled": all_day.is_disabled(),
            },
            "save": {
                "enabled": save.is_enabled(),
                "disabled": save.is_disabled(),
                "aria_invalid": save.get_attribute("aria-invalid"),
            },
            "validation_messages": [
                message.strip()[:300]
                for message in validation_messages
                if message.strip()
            ],
        }
        self.logger.info("TIMETREE_EVENT_FORM_STATE values=%s", state)
        return state

    def _validate_event_form(
        self,
        page: Page,
        spec: TestEventSpec,
    ) -> dict[str, Any]:
        state = self._event_form_state(page)
        expected = {
            "title": spec.title,
            "start_time": "7:00 PM",
            "end_time": "8:00 PM",
        }
        errors = [
            f"{field} expected {value!r}, got {state[field]['value']!r}"
            for field, value in expected.items()
            if state[field]["value"] != value
        ]
        errors.extend(
            f"{field} is aria-invalid"
            for field in expected
            if state[field]["aria_invalid"] == "true"
        )
        for field in ("start_date", "end_date"):
            if state[field].get("date") != spec.event_date.isoformat():
                errors.append(
                    f"{field} expected date {spec.event_date.isoformat()!r}, "
                    f"got {state[field].get('date')!r}"
                )
            if state[field]["aria_invalid"] == "true":
                errors.append(f"{field} is aria-invalid")
        if state["all_day"]["checked"]:
            errors.append("all-day remained enabled")
        if state["validation_messages"]:
            errors.append("validation messages are present")
        if not state["save"]["enabled"] or state["save"]["disabled"]:
            errors.append("Save is disabled")
        if errors:
            raise EventFormInvalid(
                "Event form is invalid; refusing to click Save: " + "; ".join(errors)
            )
        return state

    def _fill_title(self, page: Page, value: str) -> bool:
        title_input = unique_visible(
            (page.locator(EVENT_TITLE_FIELD_SELECTOR),),
            "fill event title",
        )
        if title_input is None:
            return False
        title_input.fill(value)
        return True

    def _resolve_created_event_url(self, page: Page, spec: TestEventSpec) -> str:
        if derive_event_id(page.url):
            return page.url
        self._dismiss_release_announcement(page)
        exact_title = page.get_by_text(spec.title, exact=True)
        visible_candidates: list[Any] = []
        event_urls: set[str] = set()
        for index in range(exact_title.count()):
            candidate = exact_title.nth(index)
            if not candidate.is_visible():
                continue
            visible_candidates.append(candidate)
            href = candidate.get_attribute("href")
            if href:
                event_url = urljoin(page.url, href)
                if derive_event_id(event_url):
                    event_urls.add(event_url)
        if len(event_urls) == 1:
            self._navigate(page, event_urls.pop(), "open_created_event")
            return page.url
        if len(event_urls) > 1:
            raise OwnershipError(
                "Created title matched multiple event URLs; refusing to guess which event is owned."
            )
        if len(visible_candidates) == 1:
            visible_candidates[0].click()
            page.wait_for_timeout(500)
            if derive_event_id(page.url):
                return page.url
        elif len(visible_candidates) > 1:
            raise OwnershipError(
                "Created title matched multiple visible elements without a unique event URL; refusing to guess."
            )
        raise OwnershipError(
            "Created title was not linked to a stable TimeTree event URL. The operation is not safe to manage later."
        )

    def _dismiss_release_announcement(self, page: Page) -> bool:
        card = page.locator("aside[data-test-id='release-announcement-card']")
        close = page.locator(
            "aside[data-test-id='release-announcement-card'] "
            "button[data-test-id='release-announcement-card--close']"
        )
        card_count = card.count()
        close_count = close.count()
        if card_count == 0 and close_count == 0:
            return False
        if card_count != 1 or close_count != 1:
            raise OwnershipError(
                "Release announcement card or its dedicated Close control was not unique; "
                "refusing to click."
            )
        card_item = card.nth(0)
        close_item = close.nth(0)
        if not card_item.is_visible() and not close_item.is_visible():
            return False
        if not card_item.is_visible() or not close_item.is_visible():
            raise OwnershipError(
                "Release announcement card visibility was inconsistent; refusing to click."
            )
        close_item.click()
        try:
            card_item.wait_for(
                state="hidden",
                timeout=min(self.config.timeout_ms, 5_000),
            )
        except PlaywrightTimeoutError as exc:
            raise OwnershipError(
                "Release announcement card did not close; refusing to resolve the created event."
            ) from exc
        self.logger.info("TIMETREE_RELEASE_ANNOUNCEMENT_CLOSED")
        return True

    def _open_owned_event(self, page: Page, record: OwnedEventRecord) -> None:
        self._navigate(page, record.event_url, "open_owned_event")
        if self._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired while opening an owned event.")
        self._wait_for_owned_event_title(page, record)
        visible_text = page.locator("body").inner_text()
        assert_owned_page(record, page.url, visible_text)

    def _wait_for_owned_event_title(self, page: Page, record: OwnedEventRecord) -> None:
        assert_record_owned(record)
        self._wait_for_event_detail_title(
            page,
            expected_title=record.current_title,
            expected_event_id=record.event_id,
        )

    def _wait_for_event_detail_title(
        self,
        page: Page,
        *,
        expected_title: str,
        expected_event_id: str,
    ) -> None:
        current_id = assert_safe_event_url(page.url)
        if current_id != expected_event_id:
            raise OwnershipError("Current page event ID does not match the owned record.")

        try:
            page.wait_for_function(
                """
                expectedTitle => {
                  const visible = element => Boolean(
                    element.offsetWidth || element.offsetHeight || element.getClientRects().length
                  );
                  const titles = Array.from(
                    document.querySelectorAll("h1[data-test-id='event-title']")
                  ).filter(visible);
                  return titles.length === 1 && titles[0].innerText.trim() === expectedTitle;
                }
                """,
                arg=expected_title,
                timeout=self.config.timeout_ms,
                polling=100,
            )
        except PlaywrightTimeoutError as exc:
            raise OwnershipError(
                "The exact stored PoC title did not become uniquely visible in the event detail title."
            ) from exc

        visible_titles = page.locator(
            "h1[data-test-id='event-title']"
        ).evaluate_all(
            """
            titles => titles
              .filter(title => title.offsetWidth || title.offsetHeight || title.getClientRects().length)
              .map(title => title.innerText.trim())
            """
        )
        if visible_titles != [expected_title]:
            raise OwnershipError(
                "The event detail title is not the unique exact stored PoC title."
            )

    def _verify_event_after_update(
        self,
        page: Page,
        record: OwnedEventRecord,
        expected_title: str,
    ) -> None:
        self._navigate(page, record.event_url, "verify_updated_event")
        if self._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired while verifying an update.")
        self._wait_for_event_detail_title(
            page,
            expected_title=expected_title,
            expected_event_id=record.event_id,
        )
        visible_text = page.locator("body").inner_text()
        if expected_title not in visible_text or record.ownership_token not in visible_text:
            raise RuntimeError(
                "Updated title and ownership token were not visible after reopening the event."
            )

    def _verify_event_deleted(self, page: Page, record: OwnedEventRecord) -> None:
        self._navigate(page, record.event_url, "verify_deleted_event")
        if self._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired while verifying a deletion.")
        visible_text = page.locator("body").inner_text()
        if record.current_title in visible_text or record.ownership_token in visible_text:
            raise RuntimeError("The owned event still appears to exist after delete confirmation.")

    def _open_event_action(self, page: Page, names: tuple[str, ...], action: str) -> None:
        more = unique_role_locator(page, "button", MORE_NAMES, "open owned event action menu")
        if more is None:
            raise SelectorNotFound(f"Could not find event action menu by accessible name: {MORE_NAMES}")
        more.click()
        control = unique_role_locator(page, "menuitem", names, f"select {action} action")
        if control is None:
            control = unique_role_locator(page, "button", names, f"select {action} action")
        if control is None:
            control = unique_role_locator(page, "link", names, f"select {action} action")
        if control is None:
            raise SelectorNotFound(f"Could not find {action} action by accessible name: {names}")
        control.click()

    def _require_calendar_name(self) -> str:
        if not self.config.calendar_name:
            raise ValueError(
                "TIMETREE_CALENDAR_NAME or --calendar is required. The PoC never guesses a target calendar."
            )
        return self.config.calendar_name
