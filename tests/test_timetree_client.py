from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.timetree.__main__ import _parse_create_date
from app.timetree.client import (
    AuthenticationRequired,
    CalendarNotFound,
    EventFormInvalid,
    TimeTreeClient,
)
from app.timetree.config import TimeTreeConfig
from app.timetree.models import CalendarInfo
from app.timetree.ownership import OwnershipError, build_test_event
from app.timetree.selectors import SelectorNotFound


class FakeCandidate:
    def __init__(self, visible: bool) -> None:
        self._visible = visible

    def is_visible(self) -> bool:
        return self._visible


class FakeLocator:
    def __init__(self, *, visible: bool = False, count: int | None = None) -> None:
        self._candidates = [FakeCandidate(visible)] if count is None else [FakeCandidate(False)] * count

    def count(self) -> int:
        return len(self._candidates)

    def nth(self, index: int) -> FakeCandidate:
        return self._candidates[index]


class FakePage:
    def __init__(
        self,
        url: str,
        *,
        email_visible: bool = False,
        sign_in_visible: bool = False,
        calendar_link_count: int = 0,
    ) -> None:
        self.url = url
        self.email_visible = email_visible
        self.sign_in_visible = sign_in_visible
        self.calendar_link_count = calendar_link_count
        self.closed = False
        self.wait_calls = 0
        self.on_wait = None

    def is_closed(self) -> bool:
        return self.closed

    def get_by_label(self, name: str, *, exact: bool = False) -> FakeLocator:
        return FakeLocator(visible=self.email_visible and name == "Email Address")

    def get_by_role(self, role: str, *, name: str, exact: bool = False) -> FakeLocator:
        visible = self.sign_in_visible and name in ("Sign in", "Log in", "ログイン", "サインイン")
        return FakeLocator(visible=visible)

    def locator(self, selector: str) -> FakeLocator:
        if selector == "input[type='email']":
            return FakeLocator(visible=self.email_visible)
        if selector == "a[href*='/calendars/']":
            return FakeLocator(count=self.calendar_link_count)
        return FakeLocator()

    def goto(self, url: str, *, wait_until: str) -> None:
        self.url = url

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.wait_calls += 1
        if self.on_wait is not None:
            self.on_wait()


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages

    def storage_state(self, *, path: str) -> None:
        Path(path).write_text('{"cookies": [], "origins": []}', encoding="utf-8")


class FakeSpaPage(FakePage):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.wait_for_function_calls: list[dict] = []

    def wait_for_function(self, expression: str, *, timeout: int, polling: int) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "timeout": timeout, "polling": polling}
        )

    def evaluate(self, expression: str) -> dict:
        return {
            "readyState": "complete",
            "interactiveElementCount": 7,
            "bodyTextLength": 120,
            "calendarLinkCandidateCount": 2,
        }

    def title(self) -> str:
        return "Private calendar - TimeTree"


class ActionCandidate:
    def __init__(self, *, visible: bool = True) -> None:
        self._visible = visible
        self.clicked = False
        self.waited = False

    def is_visible(self) -> bool:
        return self._visible

    def click(self) -> None:
        self.clicked = True

    def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "visible"
        assert timeout > 0
        self.waited = True


class ActionLocator:
    def __init__(self, candidates: list[ActionCandidate]) -> None:
        self._candidates = candidates

    @property
    def first(self) -> ActionCandidate:
        return self._candidates[0]

    def count(self) -> int:
        return len(self._candidates)

    def nth(self, index: int) -> ActionCandidate:
        return self._candidates[index]

    def fill(self, value: str) -> None:
        if len(self._candidates) != 1:
            raise PlaywrightTimeoutError("strict locator did not resolve exactly once")
        self._candidates[0].fill(value)


class CreateFormPage:
    def __init__(self, create_control_count: int) -> None:
        self.create_controls = [ActionCandidate() for _ in range(create_control_count)]
        self.title_field = ActionCandidate()
        self.wait_for_function_calls: list[dict] = []

    def get_by_role(self, role: str, *, name: str, exact: bool = False) -> ActionLocator:
        assert exact is True
        if role == "button" and name == "Create an event":
            return ActionLocator(self.create_controls)
        return ActionLocator([])

    def locator(self, selector: str) -> ActionLocator:
        if selector == "textarea[name='title'][placeholder='Event title (required)']":
            return ActionLocator([self.title_field])
        return ActionLocator([])

    def wait_for_function(
        self,
        expression: str,
        *,
        arg: dict,
        timeout: int,
        polling: int,
    ) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "arg": arg, "timeout": timeout, "polling": polling}
        )


class CalendarIdentityPage:
    def __init__(self, url: str, title: str, *, settled_title: str | None = None) -> None:
        self.url = url
        self._title = title
        self.settled_title = settled_title
        self.wait_error = False
        self.goto_calls: list[str] = []
        self.wait_for_function_calls: list[dict] = []

    def title(self) -> str:
        return self._title

    def goto(self, url: str, *, wait_until: str) -> None:
        self.goto_calls.append(url)
        self.url = url

    def wait_for_function(
        self,
        expression: str,
        *,
        arg: str,
        timeout: int,
        polling: int,
    ) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "arg": arg, "timeout": timeout, "polling": polling}
        )
        if self.wait_error:
            raise PlaywrightTimeoutError("identity timeout")
        if self.settled_title is not None:
            self._title = self.settled_title

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class CalendarDiscoveryPage:
    def __init__(self, *, wait_error: bool = False) -> None:
        self.wait_error = wait_error
        self.wait_for_function_calls: list[dict] = []

    def wait_for_function(
        self,
        expression: str,
        *,
        arg: dict[str, str],
        timeout: int,
        polling: int,
    ) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "arg": arg, "timeout": timeout, "polling": polling}
        )
        if self.wait_error:
            raise PlaywrightTimeoutError("calendar discovery timeout")


class EventTitleLocator:
    def __init__(self, page: "EventDetailPage") -> None:
        self.page = page

    def evaluate_all(self, expression: str) -> list[str]:
        return list(self.page.visible_titles)


class EventDetailPage:
    def __init__(
        self,
        url: str,
        *,
        visible_titles: list[str] | None = None,
        settled_titles: list[str] | None = None,
        wait_error: bool = False,
    ) -> None:
        self.url = url
        self.visible_titles = list(visible_titles or [])
        self.settled_titles = settled_titles
        self.wait_error = wait_error
        self.wait_for_function_calls: list[dict] = []

    def wait_for_function(
        self,
        expression: str,
        *,
        arg: str,
        timeout: int,
        polling: int,
    ) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "arg": arg, "timeout": timeout, "polling": polling}
        )
        if self.wait_error:
            raise PlaywrightTimeoutError("event title timeout")
        if self.settled_titles is not None:
            self.visible_titles = list(self.settled_titles)

    def locator(self, selector: str) -> EventTitleLocator:
        assert selector == "h1[data-test-id='event-title']"
        return EventTitleLocator(self)


class FormControl:
    def __init__(self, *, value: str = "", enabled: bool = True) -> None:
        self.value = value
        self.enabled = enabled
        self.clicked = False
        self.pressed: list[str] = []

    def is_visible(self) -> bool:
        return True

    def fill(self, value: str) -> None:
        self.value = value

    def input_value(self) -> str:
        return self.value

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def is_enabled(self) -> bool:
        return self.enabled

    def is_disabled(self) -> bool:
        return not self.enabled

    def click(self) -> None:
        self.clicked = True


class EditFormPage:
    def __init__(
        self,
        *,
        title_fields: list[FormControl] | None = None,
        settled_title_fields: list[FormControl] | None = None,
        generic_fields: list[FormControl] | None = None,
        wait_error: bool = False,
    ) -> None:
        self.title_fields = list(title_fields or [])
        self.settled_title_fields = settled_title_fields
        self.generic_fields = list(generic_fields or [])
        self.wait_error = wait_error
        self.wait_for_function_calls: list[dict] = []

    def wait_for_function(
        self,
        expression: str,
        *,
        arg: dict,
        timeout: int,
        polling: int,
    ) -> None:
        self.wait_for_function_calls.append(
            {"expression": expression, "arg": arg, "timeout": timeout, "polling": polling}
        )
        if self.wait_error:
            raise PlaywrightTimeoutError("edit title timeout")
        if self.settled_title_fields is not None:
            self.title_fields = list(self.settled_title_fields)

    def locator(self, selector: str) -> ActionLocator:
        if selector == "textarea[name='title'][placeholder='Event title (required)']":
            return ActionLocator(self.title_fields)
        if selector in ("textarea", "input", "[contenteditable]"):
            return ActionLocator(self.generic_fields)
        return ActionLocator([])

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None


class SingleControlPage:
    def __init__(self, control: FormControl) -> None:
        self.control = control

    def locator(self, selector: str) -> ActionLocator:
        return ActionLocator([self.control])  # type: ignore[list-item]


class OverlayElement:
    def __init__(
        self,
        *,
        visible: bool = True,
        href: str | None = None,
        on_click=None,
        in_monthly: bool = False,
        in_detail: bool = False,
        in_search: bool = False,
        is_detail_title: bool = False,
    ) -> None:
        self.visible = visible
        self.href = href
        self.on_click = on_click
        self.click_count = 0
        self.wait_states: list[str] = []
        self.representation = {
            "inMonthlyCalendar": in_monthly,
            "inEventDetail": in_detail,
            "inSearchField": in_search,
            "isDetailTitle": is_detail_title,
        }

    def is_visible(self) -> bool:
        return self.visible

    def click(self) -> None:
        self.click_count += 1
        if self.on_click is not None:
            self.on_click()

    def wait_for(self, *, state: str, timeout: int) -> None:
        self.wait_states.append(state)
        assert timeout <= 5_000

    def get_attribute(self, name: str) -> str | None:
        return self.href if name == "href" else None

    def evaluate(self, expression: str):
        return self.href


class OverlayLocator:
    def __init__(self, elements: list[OverlayElement]) -> None:
        self.elements = elements

    def count(self) -> int:
        return len(self.elements)

    def nth(self, index: int) -> OverlayElement:
        return self.elements[index]

    def evaluate_all(self, expression: str):
        return [element.representation for element in self.elements if element.visible]


class AnnouncementPage:
    CARD = "aside[data-test-id='release-announcement-card']"
    CLOSE = (
        "aside[data-test-id='release-announcement-card'] "
        "button[data-test-id='release-announcement-card--close']"
    )

    def __init__(
        self,
        *,
        cards: list[OverlayElement] | None = None,
        closes: list[OverlayElement] | None = None,
        title_elements: list[OverlayElement] | None = None,
    ) -> None:
        self.url = "https://timetreeapp.com/calendars/calendar-1"
        self.cards = cards or []
        self.closes = closes or []
        self.title_elements = title_elements or []
        self.title_queries: list[tuple[str, bool]] = []

    def locator(self, selector: str) -> OverlayLocator:
        if selector == self.CARD:
            return OverlayLocator(self.cards)
        if selector == self.CLOSE:
            return OverlayLocator(self.closes)
        # Unrelated aria-label=Close controls are deliberately invisible to
        # the dedicated announcement selector.
        return OverlayLocator([])

    def get_by_text(self, text: str, *, exact: bool) -> OverlayLocator:
        self.title_queries.append((text, exact))
        return OverlayLocator(self.title_elements)

    def wait_for_timeout(self, milliseconds: int) -> None:
        return None

    def wait_for_function(self, expression: str, *, arg, timeout: int, polling: int) -> None:
        return None


class SearchCalendarLocator:
    def __init__(self, results: list[OverlayElement]) -> None:
        self.results = results

    def get_by_text(self, text: str, *, exact: bool) -> OverlayLocator:
        assert exact is True
        return OverlayLocator(self.results)


class EventSearchPage:
    def __init__(self, result_count: int = 1, *, wait_error: bool = False) -> None:
        self.search_control = FormControl()
        self.search_input = FormControl()
        self.results = [OverlayElement(in_monthly=True) for _ in range(result_count)]
        self.wait_error = wait_error
        self.wait_calls: list[dict] = []

    def locator(self, selector: str):
        if selector == "[data-test-id='search-field'][role='button']":
            return ActionLocator([self.search_control])
        if selector == "input[name='search-field'][placeholder='Enter keywords to search']":
            return ActionLocator([self.search_input])
        if selector == "[data-test-id='monthly-calendar']":
            return SearchCalendarLocator(self.results)
        return ActionLocator([])

    def wait_for_function(self, expression: str, **kwargs) -> None:
        self.wait_calls.append({"expression": expression, **kwargs})
        if self.wait_error:
            raise PlaywrightTimeoutError("search timeout")


class TextLocator:
    def __init__(self, value: str) -> None:
        self.value = value

    def inner_text(self) -> str:
        return self.value


class ReconcilePage:
    def __init__(self, url: str, body_text: str) -> None:
        self.url = url
        self.body_text = body_text

    def locator(self, selector: str) -> TextLocator:
        assert selector == "body"
        return TextLocator(self.body_text)


def test_authenticated_entry_url_uses_observed_private_route(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    observed_url = "https://timetreeapp.com/calendars/calendar-1"

    client._save_auth_metadata(observed_url)

    assert client._authenticated_entry_url() == observed_url
    assert client.config.auth_metadata_path.stat().st_mode & 0o777 == 0o600


def test_authenticated_entry_url_rejects_public_or_non_timetree_route(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    client.config.auth_metadata_path.write_text(
        json.dumps(
            {
                "version": 1,
                "authenticated_entry_url": "https://example.com/calendars/calendar-1",
            }
        ),
        encoding="utf-8",
    )
    assert client._authenticated_entry_url() == "https://timetreeapp.com"

    client.config.auth_metadata_path.write_text(
        json.dumps(
            {
                "version": 1,
                "authenticated_entry_url": "https://timetreeapp.com/intl/ja",
            }
        ),
        encoding="utf-8",
    )
    assert client._authenticated_entry_url() == "https://timetreeapp.com"


@pytest.mark.parametrize(
    ("url", "required", "reason"),
    (
        ("https://timetreeapp.com/signin", True, "public_route"),
        ("https://timetreeapp.com/intl/ja", True, "public_route"),
        ("https://timetreeapp.com/calendars/WedJTLDzLQkN", False, "authenticated_app_route"),
        ("https://timetreeapp.com/about", True, "no_authenticated_evidence"),
        ("https://example.com/calendars/WedJTLDzLQkN", True, "non_timetree_url"),
    ),
)
def test_auth_assessment_fails_closed_except_for_authenticated_app_routes(
    tmp_path, url, required, reason
) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    assessment = client._assess_auth(FakePage(url))

    assert assessment.required is required
    assert assessment.reason == reason


def test_auth_assessment_rejects_login_dom_even_on_an_app_route(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    assessment = client._assess_auth(
        FakePage(
            "https://timetreeapp.com/calendars/WedJTLDzLQkN",
            email_visible=True,
        )
    )

    assert assessment.required is True
    assert assessment.reason == "email_login_field"


def test_login_pumps_playwright_events_detects_new_tab_and_saves_session(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", headless=False)
    )
    public_page = FakePage("https://timetreeapp.com/intl/ja")
    login_page = FakePage("https://timetreeapp.com/signin", email_visible=True)
    context = FakeContext([public_page, login_page])
    authenticated_page = FakePage("https://timetreeapp.com/calendars/WedJTLDzLQkN")

    def complete_login() -> None:
        login_page.closed = True
        if authenticated_page not in context.pages:
            context.pages.append(authenticated_page)

    login_page.on_wait = complete_login

    @contextmanager
    def fake_session(*args, **kwargs):
        yield login_page, context

    client._session = fake_session  # type: ignore[method-assign]

    state_path = client.login(wait_seconds=1)

    assert login_page.wait_calls >= 1
    assert state_path == client.config.storage_state_path
    assert state_path.exists()
    assert state_path.stat().st_mode & 0o777 == 0o600
    metadata = json.loads(client.config.auth_metadata_path.read_text(encoding="utf-8"))
    assert metadata["authenticated_entry_url"] == authenticated_page.url
    assert client.config.auth_metadata_path.stat().st_mode & 0o777 == 0o600


def test_login_wait_detects_same_page_navigation_after_playwright_event_pump(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    login_page = FakePage("https://timetreeapp.com/signin", email_visible=True)
    context = FakeContext([login_page])

    def complete_login() -> None:
        login_page.url = "https://timetreeapp.com/calendars/WedJTLDzLQkN"
        login_page.email_visible = False

    login_page.on_wait = complete_login

    authenticated_page = client._wait_for_authenticated_page(
        context,
        login_page,
        wait_seconds=1,
    )

    assert authenticated_page is login_page
    assert login_page.wait_calls >= 1


def test_login_timeout_fails_closed_without_writing_auth_files(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", headless=False)
    )
    login_page = FakePage("https://timetreeapp.com/signin", email_visible=True)
    context = FakeContext([login_page])

    @contextmanager
    def fake_session(*args, **kwargs):
        yield login_page, context

    client._session = fake_session  # type: ignore[method-assign]

    with pytest.raises(AuthenticationRequired, match="did not complete"):
        client.login(wait_seconds=0)

    assert not client.config.storage_state_path.exists()
    assert not client.config.auth_metadata_path.exists()


def test_navigation_waits_for_observed_react_shell_on_authenticated_route(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=12_345)
    )
    page = FakeSpaPage("about:blank")

    client._navigate(page, "https://timetreeapp.com/calendars", "home")

    assert len(page.wait_for_function_calls) == 1
    call = page.wait_for_function_calls[0]
    assert call["timeout"] == 12_345
    assert call["polling"] == 100
    assert "#react-root" in call["expression"]
    assert ".loading" in call["expression"]
    assert "button" in call["expression"]
    assert "Create an event" in call["expression"]


def test_navigation_does_not_wait_for_app_shell_on_public_route(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = FakeSpaPage("about:blank")

    client._navigate(page, "https://timetreeapp.com/signin", "login")

    assert page.wait_for_function_calls == []


def test_debug_page_diagnostics_contains_counts_without_body_text(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", debug=True)
    )
    page = FakeSpaPage("https://timetreeapp.com/calendars")

    diagnostics = client._page_diagnostics(page)

    assert diagnostics == {
        "ready_state": "complete",
        "url": "https://timetreeapp.com/calendars",
        "interactive_element_count": 7,
        "body_text_length": 120,
        "calendar_link_candidate_count": 2,
        "page_title": "TimeTree",
    }
    assert "body_text" not in diagnostics


def test_calendar_discovery_returns_immediately_when_target_is_ready(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarDiscoveryPage()
    expected = [CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/one")]
    client._calendar_links = lambda observed_page, expand: expected  # type: ignore[method-assign]

    assert client._discover_calendar_candidates(page, "Partner") == expected
    assert page.wait_for_function_calls == []


def test_calendar_discovery_waits_for_delayed_target_row(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=12_345)
    )
    page = CalendarDiscoveryPage()
    expected = [CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/one")]
    client._calendar_links = lambda observed_page, expand: []  # type: ignore[method-assign]
    client._read_calendar_links = lambda observed_page: expected  # type: ignore[method-assign]

    assert client._discover_calendar_candidates(page, "Partner") == expected
    assert len(page.wait_for_function_calls) == 1
    call = page.wait_for_function_calls[0]
    assert call["arg"] == {
        "expectedName": "Partner",
        "showOnlyName": "Show only this calendar",
    }
    assert call["timeout"] == 12_345
    assert call["polling"] == 100
    assert "a[href*='/calendars/']" in call["expression"]
    assert "semanticCalendarRow" in call["expression"]


def test_calendar_discovery_timeout_with_no_candidates_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarDiscoveryPage(wait_error=True)
    client._calendar_links = lambda observed_page, expand: []  # type: ignore[method-assign]
    client._read_calendar_links = lambda observed_page: []  # type: ignore[method-assign]

    with pytest.raises(CalendarNotFound, match="found 0"):
        client._resolve_calendar(page, "Partner")


def test_calendar_discovery_with_only_other_target_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarDiscoveryPage(wait_error=True)
    others = [CalendarInfo(name="Other", url="https://timetreeapp.com/calendars/other")]
    client._calendar_links = lambda observed_page, expand: others  # type: ignore[method-assign]
    client._read_calendar_links = lambda observed_page: others  # type: ignore[method-assign]

    with pytest.raises(CalendarNotFound, match="found 0"):
        client._resolve_calendar(page, "Partner")


def test_duplicate_calendar_names_fail_closed_without_waiting(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarDiscoveryPage()
    duplicates = [
        CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/one"),
        CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/two"),
    ]
    client._calendar_links = lambda observed_page, expand: duplicates  # type: ignore[method-assign]

    with pytest.raises(CalendarNotFound, match="found 2"):
        client._resolve_calendar(page, "Partner")

    assert page.wait_for_function_calls == []


def test_target_row_on_different_current_calendar_is_not_adopted(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/other",
        "Other - TimeTree",
    )
    page.wait_error = True
    target_without_verified_url = [CalendarInfo(name="Partner", url="")]
    client._calendar_links = (  # type: ignore[method-assign]
        lambda observed_page, expand: target_without_verified_url
    )

    with pytest.raises(CalendarNotFound, match="does not match"):
        client._resolve_calendar(page, "Partner")

    assert page.goto_calls == []


def _owned_event(client: TimeTreeClient):
    spec = build_test_event(date(2026, 9, 28))
    return client.registry.add(
        spec=spec,
        calendar_name="Partner",
        event_url="https://timetreeapp.com/calendars/calendar-1/events/event-123",
    )


def test_owned_event_title_immediately_visible_passes(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EventDetailPage(record.event_url, visible_titles=[record.current_title])

    client._wait_for_owned_event_title(page, record)

    assert len(page.wait_for_function_calls) == 1
    assert page.wait_for_function_calls[0]["arg"] == record.current_title


def test_owned_event_title_delayed_until_after_shell_wait_passes(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=12_345)
    )
    record = _owned_event(client)
    page = EventDetailPage(record.event_url, settled_titles=[record.current_title])

    client._wait_for_owned_event_title(page, record)

    call = page.wait_for_function_calls[0]
    assert call["timeout"] == 12_345
    assert call["polling"] == 100
    assert "h1[data-test-id='event-title']" in call["expression"]
    assert page.visible_titles == [record.current_title]


def test_updated_event_verification_waits_for_new_exact_title(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    updated_title = f"[HOME-SERVER-POC] Updated [{record.ownership_token}]"
    page = EventDetailPage(record.event_url, settled_titles=[updated_title])

    client._wait_for_event_detail_title(
        page,
        expected_title=updated_title,
        expected_event_id=record.event_id,
    )

    assert page.visible_titles == [updated_title]


def test_owned_event_title_timeout_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EventDetailPage(record.event_url, wait_error=True)

    with pytest.raises(OwnershipError, match="did not become uniquely visible"):
        client._wait_for_owned_event_title(page, record)


def test_different_owned_event_title_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EventDetailPage(
        record.event_url,
        visible_titles=["[HOME-SERVER-POC] Different title"],
        wait_error=True,
    )

    with pytest.raises(OwnershipError, match="did not become uniquely visible"):
        client._wait_for_owned_event_title(page, record)


def test_ownership_token_in_different_title_does_not_pass(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EventDetailPage(
        record.event_url,
        visible_titles=[f"[HOME-SERVER-POC] Different [{record.ownership_token}]"],
        wait_error=True,
    )

    with pytest.raises(OwnershipError, match="did not become uniquely visible"):
        client._wait_for_owned_event_title(page, record)


def test_owned_event_title_rejects_different_event_url_before_wait(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EventDetailPage(
        "https://timetreeapp.com/calendars/calendar-1/events/different",
        visible_titles=[record.current_title],
    )

    with pytest.raises(OwnershipError, match="event ID does not match"):
        client._wait_for_owned_event_title(page, record)

    assert page.wait_for_function_calls == []


def test_update_dry_run_verifies_ownership_without_opening_edit_or_save(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    verified: list[str] = []

    @contextmanager
    def fake_session(*args, **kwargs):
        yield object(), object()

    client._session = fake_session  # type: ignore[method-assign]
    client._open_owned_event = (  # type: ignore[method-assign]
        lambda page, owned: verified.append(owned.record_id)
    )
    client._open_event_action = (  # type: ignore[method-assign]
        lambda *args, **kwargs: pytest.fail("dry-run must not open edit or Save")
    )

    result = client.update_event(
        record_id=record.record_id,
        title="Updated",
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert verified == [record.record_id]
    assert client.registry.get(record.record_id) == record


def test_update_ownership_failure_performs_no_write(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)

    @contextmanager
    def fake_session(*args, **kwargs):
        yield object(), object()

    client._session = fake_session  # type: ignore[method-assign]
    client._open_owned_event = (  # type: ignore[method-assign]
        lambda page, owned: (_ for _ in ()).throw(OwnershipError("verification failed"))
    )
    client._open_event_action = (  # type: ignore[method-assign]
        lambda *args, **kwargs: pytest.fail("failed ownership must not open edit or Save")
    )

    with pytest.raises(OwnershipError, match="verification failed"):
        client.update_event(
            record_id=record.record_id,
            title="Updated",
            dry_run=False,
        )

    assert client.registry.get(record.record_id) == record


def test_edit_title_field_immediately_available_with_stored_value(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    field = FormControl(value="Stored title")
    page = EditFormPage(title_fields=[field])

    result = client._wait_for_event_title_field(
        page,
        expected_value="Stored title",
        action="edit form",
    )

    assert result is field
    assert len(page.wait_for_function_calls) == 1


def test_edit_title_field_delayed_until_spa_render(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=12_345)
    )
    field = FormControl(value="Stored title")
    page = EditFormPage(settled_title_fields=[field])

    result = client._wait_for_event_title_field(
        page,
        expected_value="Stored title",
        action="edit form",
    )

    assert result is field
    call = page.wait_for_function_calls[0]
    assert call["timeout"] == 12_345
    assert call["polling"] == 100


@pytest.mark.parametrize(
    "page",
    [
        EditFormPage(wait_error=True),
        EditFormPage(
            title_fields=[FormControl(value="Stored title"), FormControl(value="Stored title")],
            wait_error=True,
        ),
        EditFormPage(generic_fields=[FormControl(value="Stored title")], wait_error=True),
        EditFormPage(title_fields=[FormControl(value="Different title")], wait_error=True),
    ],
    ids=("missing", "multiple", "generic-only", "different-current-value"),
)
def test_edit_title_field_unsafe_states_fail_closed(tmp_path, page) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    with pytest.raises(SelectorNotFound, match="did not become uniquely visible"):
        client._wait_for_event_title_field(
            page,
            expected_value="Stored title",
            action="edit form",
        )


def test_update_title_field_failure_never_clicks_save(tmp_path, monkeypatch) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    page = EditFormPage(wait_error=True)

    @contextmanager
    def fake_session(*args, **kwargs):
        yield page, object()

    client._session = fake_session  # type: ignore[method-assign]
    client._open_owned_event = lambda observed, owned: None  # type: ignore[method-assign]
    client._open_event_action = lambda *args, **kwargs: None  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.timetree.client.click_role",
        lambda *args, **kwargs: pytest.fail("Save must not be clicked"),
    )

    with pytest.raises(SelectorNotFound, match="did not become uniquely visible"):
        client.update_event(
            record_id=record.record_id,
            title="Updated",
            dry_run=False,
        )

    assert client.registry.get(record.record_id) == record


def test_update_apply_preserves_prefix_and_token_and_clicks_save_once(
    tmp_path,
    monkeypatch,
) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    record = _owned_event(client)
    field = FormControl(value=record.current_title)
    page = EditFormPage(title_fields=[field])
    save_clicks: list[str] = []

    @contextmanager
    def fake_session(*args, **kwargs):
        yield page, object()

    client._session = fake_session  # type: ignore[method-assign]
    client._open_owned_event = lambda observed, owned: None  # type: ignore[method-assign]
    client._open_event_action = lambda *args, **kwargs: None  # type: ignore[method-assign]
    client._verify_event_after_update = lambda *args, **kwargs: None  # type: ignore[method-assign]
    monkeypatch.setattr(
        "app.timetree.client.click_role",
        lambda *args, **kwargs: save_clicks.append("save"),
    )

    updated = client.update_event(
        record_id=record.record_id,
        title="Updated",
        dry_run=False,
    )

    assert save_clicks == ["save"]
    assert field.value == updated.current_title
    assert updated.current_title.startswith("[HOME-SERVER-POC] ")
    assert f"[{record.ownership_token}]" in updated.current_title
    assert updated.status == "active"


def _configured_reconcile_client(tmp_path, monkeypatch, *, observed_date="2026-09-29"):
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 29))
    client.registry.record_pending_create(spec=spec, calendar_name="Partner")
    event_url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"
    page = ReconcilePage(event_url, f"{spec.title}\n{spec.ownership_token}")

    @contextmanager
    def fake_session(*args, **kwargs):
        yield page, object()

    client._session = fake_session  # type: ignore[method-assign]
    client._open_authenticated_home = lambda observed: None  # type: ignore[method-assign]
    client._resolve_calendar = lambda observed, name: CalendarInfo(  # type: ignore[method-assign]
        name="Partner",
        url="https://timetreeapp.com/calendars/calendar-1",
    )
    client._open_calendar = lambda observed, calendar: None  # type: ignore[method-assign]
    client._search_exact_title_event_url = lambda observed, title: event_url  # type: ignore[method-assign]
    client._wait_for_event_detail_title = lambda *args, **kwargs: None  # type: ignore[method-assign]
    client._event_detail_start_date = lambda observed: observed_date  # type: ignore[method-assign]
    for forbidden in ("_open_create_form", "_save_prepared_event", "_open_event_action"):
        monkeypatch.setattr(
            client,
            forbidden,
            lambda *args, **kwargs: pytest.fail("reconciliation must not mutate TimeTree"),
        )
    return client, spec


def test_reconcile_pending_dry_run_makes_no_ledger_or_timetree_write(
    tmp_path,
    monkeypatch,
) -> None:
    client, spec = _configured_reconcile_client(tmp_path, monkeypatch)

    result = client.reconcile_pending_create(
        ownership_token=spec.ownership_token,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert client.registry.list() == []
    assert len(client.registry.list_pending_creates()) == 1


def test_reconcile_pending_apply_promotes_owned_and_clears_pending(
    tmp_path,
    monkeypatch,
) -> None:
    client, spec = _configured_reconcile_client(tmp_path, monkeypatch)

    record = client.reconcile_pending_create(
        ownership_token=spec.ownership_token,
        dry_run=False,
    )

    assert record.current_title == spec.title
    assert record.ownership_token == spec.ownership_token
    assert len(client.registry.list()) == 1
    assert client.registry.list_pending_creates() == []


def test_reconcile_pending_date_mismatch_fails_and_keeps_pending(
    tmp_path,
    monkeypatch,
) -> None:
    client, spec = _configured_reconcile_client(
        tmp_path,
        monkeypatch,
        observed_date="2026-09-30",
    )

    with pytest.raises(OwnershipError, match="date does not exactly match"):
        client.reconcile_pending_create(
            ownership_token=spec.ownership_token,
            dry_run=False,
        )

    assert client.registry.list() == []
    assert len(client.registry.list_pending_creates()) == 1


def test_empty_calendar_url_keeps_matching_current_calendar_open(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "Partner - TimeTree",
    )

    client._open_calendar(page, CalendarInfo(name="Partner", url=""))

    assert page.goto_calls == []
    assert page.url == "https://timetreeapp.com/calendars/calendar-1"


def test_resolve_calendar_waits_for_delayed_identity_and_keeps_current_url(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "TimeTree",
        settled_title="Partner - TimeTree",
    )
    client._calendar_links = (  # type: ignore[method-assign]
        lambda observed_page, expand: [CalendarInfo(name="Partner", url="")]
    )

    calendar = client._resolve_calendar(page, "Partner")

    assert calendar == CalendarInfo(
        name="Partner",
        url="https://timetreeapp.com/calendars/calendar-1",
    )
    assert len(page.wait_for_function_calls) == 1
    assert page.goto_calls == []


def test_create_event_path_does_not_leave_matching_current_calendar(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "TimeTree",
        settled_title="Partner - TimeTree",
    )
    client._calendar_links = (  # type: ignore[method-assign]
        lambda observed_page, expand: [CalendarInfo(name="Partner", url="")]
    )
    client._open_authenticated_home = lambda observed_page: None  # type: ignore[method-assign]

    class StopBeforeForm(RuntimeError):
        pass

    def stop_before_form(observed_page) -> None:
        assert observed_page.url == "https://timetreeapp.com/calendars/calendar-1"
        raise StopBeforeForm

    client._open_create_form = stop_before_form  # type: ignore[method-assign]

    @contextmanager
    def fake_session(*args, **kwargs):
        yield page, object()

    client._session = fake_session  # type: ignore[method-assign]

    with pytest.raises(StopBeforeForm):
        client.create_event(event_date=date(2026, 9, 28), dry_run=False)

    assert page.goto_calls == []


def test_different_current_calendar_fails_closed_without_click_or_navigation(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/another-calendar",
        "Another - TimeTree",
    )

    with pytest.raises(CalendarNotFound, match="no verified URL"):
        client._open_calendar(page, CalendarInfo(name="Partner", url=""))

    assert page.goto_calls == []


def test_calendar_identity_timeout_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=1_000)
    )
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "TimeTree",
    )
    page.wait_error = True

    with pytest.raises(CalendarNotFound, match="did not become"):
        client._wait_for_calendar_identity(page, "Partner")

    assert page.goto_calls == []


def test_transient_nonmatching_title_may_settle_without_navigation(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=3_000)
    )
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "Loading calendar - TimeTree",
        settled_title="Partner - TimeTree",
    )

    client._wait_for_calendar_identity(page, "Partner")

    assert page.title() == "Partner - TimeTree"
    assert page.goto_calls == []
    assert len(page.wait_for_function_calls) == 2


def test_nonmatching_title_that_does_not_settle_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", timeout_ms=3_000)
    )
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/another-calendar",
        "Another - TimeTree",
    )
    page.wait_error = True

    with pytest.raises(CalendarNotFound, match="does not match"):
        client._wait_for_calendar_identity(page, "Partner")

    assert page.goto_calls == []


def test_explicit_cli_date_remains_date_only_without_timezone_shift() -> None:
    parsed = _parse_create_date("2026-09-28")

    assert parsed == date(2026, 9, 28)
    assert parsed.isoformat() == "2026-09-28"


def test_observed_form_input_uses_fill_and_blur(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    control = FormControl()

    client._fill_observed_input(
        SingleControlPage(control),  # type: ignore[arg-type]
        "input[name='dateTime.startDate']",
        "2026-09-28",
        "start date",
    )

    assert control.value == "2026-09-28"
    assert control.pressed == ["Tab"]


def _valid_form_state(spec) -> dict:
    return {
        "url": "https://timetreeapp.com/calendars/calendar-1/events/new",
        "title": {"value": spec.title, "aria_invalid": None, "disabled": False},
        "start_date": {
            "value": "Mon, Sep 28, 2026",
            "date": "2026-09-28",
            "aria_invalid": None,
            "disabled": False,
        },
        "start_time": {"value": "7:00 PM", "aria_invalid": None, "disabled": False},
        "end_date": {
            "value": "Mon, Sep 28, 2026",
            "date": "2026-09-28",
            "aria_invalid": None,
            "disabled": False,
        },
        "end_time": {"value": "8:00 PM", "aria_invalid": None, "disabled": False},
        "all_day": {"checked": False, "aria_invalid": None, "disabled": False},
        "save": {"enabled": True, "disabled": False, "aria_invalid": None},
        "validation_messages": [],
    }


def test_validated_form_requires_exact_title_dates_and_times(tmp_path, monkeypatch) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    state = _valid_form_state(spec)
    monkeypatch.setattr(client, "_event_form_state", lambda page: state)

    assert client._validate_event_form(object(), spec) == state


def test_timetree_date_format_round_trips_without_timezone_conversion(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    displayed = client._format_timetree_date(date(2026, 9, 28))

    assert displayed == "Mon, Sep 28, 2026"
    assert client._parse_timetree_date(displayed) == "2026-09-28"


def test_disabled_save_fails_closed(tmp_path, monkeypatch) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    state = _valid_form_state(spec)
    state["save"] = {"enabled": False, "disabled": True, "aria_invalid": None}
    monkeypatch.setattr(client, "_event_form_state", lambda page: state)

    with pytest.raises(EventFormInvalid, match="Save is disabled"):
        client._validate_event_form(object(), spec)


def test_form_preparation_never_clicks_save(tmp_path, monkeypatch) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    calls: list[str] = []
    state = _valid_form_state(spec)
    monkeypatch.setattr(client, "_fill_event_form", lambda page, value: calls.append("fill"))
    monkeypatch.setattr(client, "_validate_event_form", lambda page, value: state)
    monkeypatch.setattr(
        client,
        "_save_event_control",
        lambda page: pytest.fail("form preparation must never request or click Save"),
    )

    class ReadyPage:
        def wait_for_function(self, expression, *, timeout, polling) -> None:
            return None

    assert client._prepare_event_form(ReadyPage(), spec) == state
    assert calls == ["fill"]


def test_disabled_save_is_not_clicked_and_does_not_create_pending_record(
    tmp_path,
    monkeypatch,
) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    save = FormControl(enabled=False)
    pending: list[str] = []
    monkeypatch.setattr(client, "_save_event_control", lambda page: save)
    monkeypatch.setattr(
        client.registry,
        "record_pending_create",
        lambda **kwargs: pending.append(kwargs["calendar_name"]),
    )

    with pytest.raises(EventFormInvalid, match="became disabled"):
        client._save_prepared_event(object(), spec, "Partner")

    assert save.clicked is False
    assert pending == []


def test_enabled_save_records_pending_immediately_before_click(tmp_path, monkeypatch) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    actions: list[str] = []

    class OrderedSave(FormControl):
        def click(self) -> None:
            actions.append("click")
            super().click()

    save = OrderedSave(enabled=True)
    monkeypatch.setattr(client, "_save_event_control", lambda page: save)
    monkeypatch.setattr(
        client.registry,
        "record_pending_create",
        lambda **kwargs: actions.append("pending"),
    )

    client._save_prepared_event(object(), spec, "Partner")

    assert actions == ["pending", "click"]
    assert save.clicked is True


def test_created_event_resolution_does_nothing_without_announcement(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    assert client._dismiss_release_announcement(AnnouncementPage()) is False


def test_created_event_resolution_closes_one_dedicated_announcement(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    card = OverlayElement()
    close = OverlayElement()
    page = AnnouncementPage(cards=[card], closes=[close])

    assert client._dismiss_release_announcement(page) is True
    assert close.click_count == 1
    assert card.wait_states == ["hidden"]


def test_multiple_announcement_close_controls_fail_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    closes = [OverlayElement(), OverlayElement()]
    page = AnnouncementPage(cards=[OverlayElement()], closes=closes)

    with pytest.raises(OwnershipError, match="not unique"):
        client._dismiss_release_announcement(page)

    assert all(close.click_count == 0 for close in closes)


def test_unrelated_close_control_is_never_clicked(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    unrelated = OverlayElement()
    page = AnnouncementPage()
    page.unrelated_close = unrelated

    assert client._dismiss_release_announcement(page) is False
    assert unrelated.click_count == 0


def test_created_event_title_resolution_uses_exact_title_after_announcement(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    page = AnnouncementPage(cards=[OverlayElement()], closes=[OverlayElement()])

    def open_event() -> None:
        page.url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"
        page.title_elements = [
            title,
            OverlayElement(in_detail=True, is_detail_title=True),
        ]

    title = OverlayElement(on_click=open_event, in_monthly=True)
    page.title_elements = [title]

    resolved = client._resolve_created_event_url(page, spec)

    assert resolved.endswith("/events/event-123")
    assert page.title_queries == [(spec.title, True), (spec.title, True)]
    assert title.click_count == 1


def test_missing_exact_title_after_announcement_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    spec = build_test_event(date(2026, 9, 28))
    close = OverlayElement()
    page = AnnouncementPage(cards=[OverlayElement()], closes=[close])

    with pytest.raises(OwnershipError, match="not linked"):
        client._resolve_created_event_url(page, spec)

    assert close.click_count == 1
    assert page.title_queries == [(spec.title, True)]


def test_exact_title_one_element_with_one_event_url_resolves(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = AnnouncementPage(
        title_elements=[
            OverlayElement(
                href="https://timetreeapp.com/calendars/calendar-1/events/event-123",
                in_detail=True,
                is_detail_title=True,
            )
        ]
    )
    page.url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"

    resolved = client._resolve_exact_title_event_url(page, "Owned title")

    assert resolved.endswith("/events/event-123")


def test_multiple_exact_title_representations_same_current_event_resolve(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = AnnouncementPage(
        title_elements=[
            OverlayElement(in_monthly=True),
            OverlayElement(in_detail=True, is_detail_title=True),
        ]
    )
    page.url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"

    assert client._resolve_exact_title_event_url(page, "Owned title") == page.url
    assert all(element.click_count == 0 for element in page.title_elements)


def test_search_monthly_and_detail_representations_same_event_resolve(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = AnnouncementPage(
        title_elements=[
            OverlayElement(in_search=True),
            OverlayElement(in_monthly=True),
            OverlayElement(in_detail=True, is_detail_title=True),
        ]
    )
    page.url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"

    assert client._current_exact_title_event_url(page, "Owned title") == page.url


def test_multiple_search_representations_do_not_resolve(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = AnnouncementPage(
        title_elements=[
            OverlayElement(in_search=True),
            OverlayElement(in_search=True),
            OverlayElement(in_monthly=True),
            OverlayElement(in_detail=True, is_detail_title=True),
        ]
    )
    page.url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"

    assert client._current_exact_title_event_url(page, "Owned title") is None


def test_multiple_exact_title_event_urls_fail_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = AnnouncementPage(
        title_elements=[
            OverlayElement(
                href="https://timetreeapp.com/calendars/calendar-1/events/event-1"
            ),
            OverlayElement(
                href="https://timetreeapp.com/calendars/calendar-1/events/event-2"
            ),
        ]
    )
    page.url = "https://timetreeapp.com/calendars/calendar-1"

    with pytest.raises(OwnershipError, match="multiple event URLs"):
        client._resolve_exact_title_event_url(page, "Owned title")


def test_reconciliation_search_uses_exact_unique_monthly_result(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = EventSearchPage()
    event_url = "https://timetreeapp.com/calendars/calendar-1/events/event-123"
    client._wait_for_exact_title_event_url = (  # type: ignore[method-assign]
        lambda observed, title: event_url
    )

    resolved = client._search_exact_title_event_url(page, "Exact owned title")

    assert resolved == event_url
    assert page.search_control.clicked is True
    assert page.search_input.value == "Exact owned title"
    assert page.results[0].click_count == 1


def test_reconciliation_search_multiple_exact_results_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = EventSearchPage(result_count=2)

    with pytest.raises(OwnershipError, match="found 2"):
        client._search_exact_title_event_url(page, "Exact owned title")

    assert all(result.click_count == 0 for result in page.results)


def test_reconciliation_search_timeout_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = EventSearchPage(wait_error=True)

    with pytest.raises(OwnershipError, match="search input did not become uniquely visible"):
        client._search_exact_title_event_url(page, "Exact owned title")

    assert all(result.click_count == 0 for result in page.results)


def test_post_save_resolution_failure_does_not_retry_create_and_keeps_pending(
    tmp_path,
    monkeypatch,
) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "Partner - TimeTree",
    )
    save_attempts: list[str] = []
    client._open_authenticated_home = lambda observed_page: None  # type: ignore[method-assign]
    client._resolve_calendar = lambda observed_page, name: CalendarInfo(  # type: ignore[method-assign]
        name="Partner",
        url=page.url,
    )
    client._open_calendar = lambda observed_page, calendar: None  # type: ignore[method-assign]
    client._open_create_form = lambda observed_page: None  # type: ignore[method-assign]
    client._prepare_event_form = lambda observed_page, spec: {}  # type: ignore[method-assign]

    def save_once(observed_page, spec, calendar_name) -> None:
        save_attempts.append(spec.ownership_token)
        client.registry.record_pending_create(spec=spec, calendar_name=calendar_name)

    client._save_prepared_event = save_once  # type: ignore[method-assign]
    client._resolve_created_event_url = (  # type: ignore[method-assign]
        lambda observed_page, spec: (_ for _ in ()).throw(OwnershipError("resolution failed"))
    )

    @contextmanager
    def fake_session(*args, **kwargs):
        yield page, object()

    client._session = fake_session  # type: ignore[method-assign]

    with pytest.raises(OwnershipError, match="resolution failed"):
        client.create_event(event_date=date(2026, 9, 28), dry_run=False)

    assert len(save_attempts) == 1
    assert len(client.registry.list_pending_creates()) == 1
    assert client.registry.list() == []


def test_current_calendar_url_requires_exact_title_and_canonical_route(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    current = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1?view=month",
        "Partner - TimeTree",
    )
    root = CalendarIdentityPage("https://timetreeapp.com/calendars", "Partner - TimeTree")
    wrong = CalendarIdentityPage(
        "https://timetreeapp.com/calendars/calendar-1",
        "Another - TimeTree",
    )

    assert client._current_calendar_url(current, "Partner") == (
        "https://timetreeapp.com/calendars/calendar-1"
    )
    assert client._current_calendar_url(root, "Partner") is None
    assert client._current_calendar_url(wrong, "Partner") is None


def test_create_control_is_clicked_only_when_unique_and_form_is_observed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CreateFormPage(create_control_count=1)

    client._open_create_form(page)

    assert page.create_controls[0].clicked is True
    assert len(page.wait_for_function_calls) == 1
    assert page.wait_for_function_calls[0]["arg"]["expectedValue"] is None


def test_create_control_missing_fails_closed(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))

    with pytest.raises(SelectorNotFound, match="Could not find create-event control"):
        client._open_create_form(CreateFormPage(create_control_count=0))


def test_multiple_create_controls_fail_closed_without_clicking(tmp_path) -> None:
    client = TimeTreeClient(TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner"))
    page = CreateFormPage(create_control_count=2)

    with pytest.raises(SelectorNotFound, match="expected at most one visible semantic match"):
        client._open_create_form(page)

    assert all(control.clicked is False for control in page.create_controls)
