from __future__ import annotations

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

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
    END_DATE_LABELS,
    MORE_NAMES,
    SAVE_NAMES,
    START_DATE_LABELS,
    TITLE_LABELS,
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
            deadline = time.monotonic() + wait_seconds
            authenticated_page: Page | None = None
            while time.monotonic() < deadline:
                for candidate in reversed(context.pages):
                    if not self._auth_required(candidate) and self._is_timetree_url(candidate.url):
                        authenticated_page = candidate
                        break
                if authenticated_page is not None:
                    break
                time.sleep(1)
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
            calendars = self._calendar_links(page, expand=True)
            if self.config.calendar_name:
                matches = [
                    calendar for calendar in calendars if calendar.name == self.config.calendar_name
                ]
                if len(matches) != 1:
                    raise CalendarNotFound(
                        f"Expected exactly one calendar named {self.config.calendar_name!r}; "
                        f"found {len(matches)}. Available link names: {[item.name for item in calendars]}"
                    )
                self.logger.info(
                    "TIMETREE_CALENDAR_FOUND name=%s url=%s",
                    matches[0].name,
                    matches[0].url,
                )
            return calendars

    def probe(self, *, surface: str = "home", record_id: str | None = None) -> dict[str, str]:
        with self._session("probe") as (page, _):
            self._open_authenticated_home(page)
            if surface == "create":
                calendar = self._resolve_calendar(page, self._require_calendar_name())
                self._open_calendar(page, calendar)
                self._open_create_form(page)
            elif surface == "owned":
                self._open_owned_event(page, self.registry.get(record_id))
            elif surface != "home":
                raise ValueError(f"Unsupported probe surface: {surface}")
            slug = timestamp_slug()
            destination = self.config.artifacts_dir / f"{slug}_probe_{surface}"
            destination.mkdir(parents=True, exist_ok=True)
            destination.chmod(0o700)
            screenshot_path = destination / "page.png"
            elements_path = destination / "interactive-elements.json"
            page.screenshot(path=str(screenshot_path), full_page=True)
            screenshot_path.chmod(0o600)
            elements = page.locator(
                "a,button,input,textarea,select,[role],[aria-label],[data-testid]"
            ).evaluate_all(
                """
                elements => elements.map((element) => ({
                  tag: element.tagName.toLowerCase(),
                  role: element.getAttribute('role'),
                  ariaLabel: element.getAttribute('aria-label'),
                  dataTestId: element.getAttribute('data-testid'),
                  name: element.getAttribute('name'),
                  type: element.getAttribute('type'),
                  placeholder: element.getAttribute('placeholder'),
                  href: element.getAttribute('href'),
                  text: (element.innerText || '').trim().slice(0, 300),
                })).filter(item => item.text || item.ariaLabel || item.placeholder || item.href)
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
            self._fill_event_form(page, spec)
            self.registry.record_pending_create(spec=spec, calendar_name=calendar_name)
            click_role(page, "button", SAVE_NAMES, "save/create button")
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
            if not self._fill_title(page, updated_title):
                raise SelectorNotFound("Could not find the event title field by label or stable input attribute.")
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

    def _auth_required(self, page: Page) -> bool:
        path = urlparse(page.url).path.lower()
        if not self._is_timetree_url(page.url):
            return True
        if path.startswith(("/signin", "/signup", "/forgot", "/intl/")):
            return True
        email_field = first_visible(
            (
                page.get_by_label("Email Address", exact=True),
                page.get_by_role("textbox", name="Email Address", exact=True),
                page.locator("input[type='email']"),
            )
        )
        if email_field is not None:
            return True
        sign_in = first_visible(
            page.get_by_role(role, name=name, exact=True)
            for role in ("link", "button")
            for name in ("Sign in", "Log in", "ログイン", "サインイン")
        )
        if sign_in is not None:
            return True

        # Authentication is deliberately fail-closed. A missing login form is
        # not enough: public marketing pages also have no form. Require a route
        # or link that belongs to the signed-in calendar application.
        app_route = any(
            path == prefix or path.startswith(f"{prefix}/")
            for prefix in ("/calendars", "/calendar", "/home", "/activity", "/events", "/settings")
        )
        if app_route:
            return False
        try:
            if page.locator("a[href*='/calendars/']").count() > 0:
                return False
        except Exception:  # noqa: BLE001,S110 - authentication checks must fail closed
            pass
        return True

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
        calendars = self._read_calendar_links(page)
        if calendars or not expand:
            return calendars
        control = role_locator(page, "button", CALENDAR_LIST_NAMES) or role_locator(
            page, "link", CALENDAR_LIST_NAMES
        )
        if control is not None:
            control.click()
            page.wait_for_timeout(500)
            calendars = self._read_calendar_links(page)
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
        return list(found.values())

    def _resolve_calendar(self, page: Page, name: str) -> CalendarInfo:
        matches = [calendar for calendar in self._calendar_links(page, expand=True) if calendar.name == name]
        if len(matches) != 1:
            available = [calendar.name for calendar in self._calendar_links(page, expand=False)]
            raise CalendarNotFound(
                f"Expected exactly one calendar named {name!r}; found {len(matches)}. Available link names: {available}"
            )
        calendar = matches[0]
        self.logger.info("TIMETREE_CALENDAR_FOUND name=%s url=%s", calendar.name, calendar.url)
        return calendar

    def _open_calendar(self, page: Page, calendar: CalendarInfo) -> None:
        if calendar.url:
            self._navigate(page, calendar.url, "open_calendar")
            return
        locator = page.get_by_text(calendar.name, exact=True)
        if locator.count() != 1 or not locator.is_visible():
            raise CalendarNotFound(f"Calendar {calendar.name!r} is not uniquely selectable.")
        locator.click()

    def _open_create_form(self, page: Page) -> None:
        control = unique_role_locator(page, "button", CREATE_EVENT_NAMES, "open create-event form")
        if control is None:
            control = unique_role_locator(page, "link", CREATE_EVENT_NAMES, "open create-event form")
        if control is None:
            raise SelectorNotFound(
                f"Could not find create-event control by accessible name: {CREATE_EVENT_NAMES}"
            )
        control.click()

    def _fill_event_form(self, page: Page, spec: TestEventSpec) -> None:
        if not self._fill_title(page, spec.title):
            raise SelectorNotFound("Could not find the event title field by label or stable input attribute.")
        date_value = spec.event_date.isoformat()
        date_filled = fill_labeled(page, START_DATE_LABELS, date_value, "start date")
        if not date_filled:
            date_input = unique_visible((page.locator("input[type='date']"),), "fill event date")
            if date_input is None:
                raise SelectorNotFound("Could not find an event date field by label or input[type=date].")
            date_input.fill(date_value)
        end_date = unique_labeled_locator(page, END_DATE_LABELS, "fill end date")
        if end_date is not None:
            end_date.fill(date_value)
        if not fill_labeled(page, DESCRIPTION_LABELS, spec.description, "description"):
            description = unique_visible(
                (page.locator("textarea[name*='description' i]"),),
                "fill event description",
            )
            if description is None:
                description = unique_visible((page.locator("textarea"),), "fill event description")
            if description is not None:
                description.fill(spec.description)
            else:
                self.logger.warning(
                    "TIMETREE_SELECTOR_OPTIONAL_MISSING field=description token_remains_in_title=true"
                )

    def _fill_title(self, page: Page, value: str) -> bool:
        if fill_labeled(page, TITLE_LABELS, value, "title"):
            return True
        title_input = None
        for selector in (
            "input[name*='title' i]",
            "input[placeholder*='title' i]",
            "input[placeholder*='予定']",
        ):
            title_input = unique_visible((page.locator(selector),), "fill event title")
            if title_input is not None:
                break
        if title_input is None:
            return False
        title_input.fill(value)
        return True

    def _resolve_created_event_url(self, page: Page, spec: TestEventSpec) -> str:
        if derive_event_id(page.url):
            return page.url
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

    def _open_owned_event(self, page: Page, record: OwnedEventRecord) -> None:
        self._navigate(page, record.event_url, "open_owned_event")
        if self._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired while opening an owned event.")
        visible_text = page.locator("body").inner_text()
        assert_owned_page(record, page.url, visible_text)

    def _verify_event_after_update(
        self,
        page: Page,
        record: OwnedEventRecord,
        expected_title: str,
    ) -> None:
        self._navigate(page, record.event_url, "verify_updated_event")
        if self._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired while verifying an update.")
        if assert_safe_event_url(page.url) != record.event_id:
            raise OwnershipError("Updated event URL no longer matches the owned record.")
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
