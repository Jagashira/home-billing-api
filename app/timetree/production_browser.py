from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.schemas.timetree import TimeTreeEventPayload, TimeTreeOperationRequest
from app.timetree.client import AuthenticationRequired, EventFormInvalid, TimeTreeClient
from app.timetree.ownership import OwnershipError, derive_event_id
from app.timetree.production_models import (
    BrowserResult,
    ProductionOperationError,
    calendar_id_from_url,
    canonical_calendar_url,
    canonical_payload_hash,
)
from app.timetree.selectors import (
    CONFIRM_DELETE_NAMES,
    DELETE_NAMES,
    EDIT_NAMES,
    NOTE_CONFIRM_NAMES,
    NOTE_NAMES,
    SelectorNotFound,
    unique_role_locator,
    unique_visible,
)


TOKYO = ZoneInfo("Asia/Tokyo")
TITLE_SELECTOR = "textarea[name='title'][placeholder='Event title (required)']"
START_DATE_SELECTOR = "input[name='dateTime.startDate'][data-test-id='start-date-picker']"
START_TIME_SELECTOR = "input[name='dateTime.startTime'][data-test-id='start-time-picker']"
END_DATE_SELECTOR = "input[name='dateTime.endDate'][data-test-id='end-date-picker']"
END_TIME_SELECTOR = "input[name='dateTime.endTime'][data-test-id='end-time-picker']"
ALL_DAY_SELECTOR = "button[role='switch'][data-test-id='allday-checkbox']"
LOCATION_SELECTOR = "input[name='location'][placeholder='Add a location']"
NOTE_BUTTON_SELECTOR = "[role='button'][data-test-id='note-input']"
NOTE_TEXTAREA_SELECTOR = "textarea[data-test-id='note-input-textarea'][placeholder='Add event details up to 10,000 characters']"


def _iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("event datetime must include a timezone")
    return parsed.astimezone(TOKYO)


def _display_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


def _iso_utc(value: datetime) -> str:
    return value.astimezone(ZoneInfo("UTC")).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _note_for(payload: TimeTreeEventPayload) -> str:
    return f"{payload.description}\n\n{payload.ownership_marker}" if payload.description else payload.ownership_marker


def _description_from_note(note: str, marker: str) -> str | None:
    if note == marker:
        return None
    suffix = f"\n\n{marker}"
    if not note.endswith(suffix) or note.count(marker) != 1:
        raise OwnershipError("The exact production ownership marker was not uniquely present in the event Note.")
    return note[: -len(suffix)] or None


class SingleWriteAttempt:
    def __init__(self) -> None:
        self.count = 0

    def click(self, control: Any) -> None:
        if self.count:
            raise RuntimeError("A TimeTree write control may be clicked only once per operation.")
        self.count = 1
        control.click()


class PlaywrightProductionBackend:
    """Production browser operations without any PoC ownership ledger dependency."""

    def __init__(self, client: TimeTreeClient) -> None:
        self.client = client

    def _verified_calendar(self, page: Any, request: TimeTreeOperationRequest) -> tuple[str, str]:
        if self.client.config.calendar_name != request.calendar.name:
            raise ProductionOperationError(
                outcome="rejected", phase="before_form", code="calendar_name_mismatch",
                message="Configured TimeTree calendar name does not match the requested mapping.",
            )
        calendar = self.client._resolve_calendar(page, request.calendar.name)
        self.client._open_calendar(page, calendar)
        current_url = self.client._current_calendar_url(page, request.calendar.name)
        calendar_id = calendar_id_from_url(current_url or "")
        if not calendar_id:
            raise ProductionOperationError(
                outcome="rejected", phase="before_form", code="calendar_identity_missing",
                message="The target calendar did not resolve to one canonical TimeTree calendar URL.",
            )
        canonical_url = canonical_calendar_url(calendar_id)
        if calendar_id != request.calendar.calendar_id or canonical_url != request.calendar.url:
            raise ProductionOperationError(
                outcome="rejected", phase="before_form", code="calendar_identity_mismatch",
                message="Resolved TimeTree calendar identity does not match the enabled database mapping.",
            )
        return calendar_id, canonical_url

    def _fill_note(self, page: Any, note_value: str) -> None:
        note = unique_visible((page.locator(NOTE_BUTTON_SELECTOR),), "open production event note")
        if note is None:
            note = unique_role_locator(page, "button", NOTE_NAMES, "open production event note")
        if note is None:
            raise SelectorNotFound("Could not uniquely identify the event Note control.")
        note.click()
        textarea = unique_visible((page.locator(NOTE_TEXTAREA_SELECTOR),), "fill production event note")
        if textarea is None:
            raise SelectorNotFound("Could not uniquely identify the event Note textarea.")
        textarea.fill(note_value)
        confirm = unique_role_locator(page, "button", NOTE_CONFIRM_NAMES, "confirm production event note")
        if confirm is None:
            raise SelectorNotFound("Could not uniquely identify the event Note confirmation control.")
        confirm.click()
        try:
            textarea.wait_for(state="hidden", timeout=self.client.config.timeout_ms)
        except PlaywrightTimeoutError as exc:
            raise EventFormInvalid("The event Note dialog did not close.") from exc

    def _fill_form(self, page: Any, payload: TimeTreeEventPayload, *, expected_title: str | None = None) -> None:
        title = self.client._wait_for_event_title_field(page, expected_value=expected_title, action="production event form")
        title.fill(payload.title)
        self.client._set_all_day(page, enabled=payload.all_day)
        if payload.all_day:
            start = date.fromisoformat(payload.start_date or "")
            end_exclusive = date.fromisoformat(payload.end_date_exclusive or "")
            if end_exclusive <= start:
                raise EventFormInvalid("All-day end_date_exclusive must be after start_date.")
            end_inclusive = end_exclusive - timedelta(days=1)
            self.client._fill_observed_input(page, START_DATE_SELECTOR, self.client._format_timetree_date(start), "start date")
            self.client._fill_observed_input(page, END_DATE_SELECTOR, self.client._format_timetree_date(end_inclusive), "end date")
        else:
            start_at = _iso_datetime(payload.start_at)
            end_at = _iso_datetime(payload.end_at)
            if end_at <= start_at:
                raise EventFormInvalid("Event end must be after start.")
            self.client._fill_observed_input(page, START_DATE_SELECTOR, self.client._format_timetree_date(start_at.date()), "start date")
            self.client._fill_observed_input(page, START_TIME_SELECTOR, _display_time(start_at), "start time")
            self.client._fill_observed_input(page, END_DATE_SELECTOR, self.client._format_timetree_date(end_at.date()), "end date")
            self.client._fill_observed_input(page, END_TIME_SELECTOR, _display_time(end_at), "end time")
        self._fill_note(page, _note_for(payload))
        location = unique_visible((page.locator(LOCATION_SELECTOR),), "fill production event location")
        if location is None:
            raise SelectorNotFound("Could not uniquely identify the observed location input.")
        location.fill(payload.location or "")
        save = self.client._save_event_control(page)
        if not save.is_enabled() or save.is_disabled():
            raise EventFormInvalid("Event form Save is disabled.")

    def _read_note(self, page: Any) -> str:
        note = unique_visible((page.locator(NOTE_BUTTON_SELECTOR),), "inspect production event note")
        if note is None:
            raise SelectorNotFound("Could not uniquely identify the event Note control.")
        note.click()
        textarea = unique_visible((page.locator(NOTE_TEXTAREA_SELECTOR),), "inspect production event note")
        if textarea is None:
            raise SelectorNotFound("Could not uniquely identify the event Note textarea.")
        value = textarea.input_value()
        confirm = unique_role_locator(page, "button", NOTE_CONFIRM_NAMES, "close production event note")
        if confirm is None:
            raise SelectorNotFound("Could not uniquely identify the event Note confirmation control.")
        confirm.click()
        return value

    def _read_form_payload(self, page: Any, request: TimeTreeOperationRequest) -> TimeTreeEventPayload:
        title = self.client._wait_for_event_title_field(page, expected_value=None, action="inspect production event")
        all_day = unique_visible((page.locator(ALL_DAY_SELECTOR),), "inspect production all-day state")
        location = unique_visible((page.locator(LOCATION_SELECTOR),), "inspect production location")
        if all_day is None or location is None:
            raise SelectorNotFound("Production event form identity fields were not uniquely visible.")
        start_date_control = unique_visible((page.locator(START_DATE_SELECTOR),), "inspect production start date")
        end_date_control = unique_visible((page.locator(END_DATE_SELECTOR),), "inspect production end date")
        if start_date_control is None or end_date_control is None:
            raise SelectorNotFound("Production event date fields were not uniquely visible.")
        start_date_value = self.client._parse_timetree_date(start_date_control.input_value())
        end_date_value = self.client._parse_timetree_date(end_date_control.input_value())
        if not start_date_value or not end_date_value:
            raise EventFormInvalid("TimeTree event dates could not be parsed safely.")
        is_all_day = all_day.get_attribute("aria-checked") == "true"
        if is_all_day:
            start_day = date.fromisoformat(start_date_value)
            end_exclusive = date.fromisoformat(end_date_value) + timedelta(days=1)
            start_at = datetime.combine(start_day, datetime_time.min, TOKYO)
            end_at = datetime.combine(end_exclusive, datetime_time.min, TOKYO)
        else:
            start_time_control = unique_visible((page.locator(START_TIME_SELECTOR),), "inspect production start time")
            end_time_control = unique_visible((page.locator(END_TIME_SELECTOR),), "inspect production end time")
            if start_time_control is None or end_time_control is None:
                raise SelectorNotFound("Production event time fields were not uniquely visible.")
            try:
                start_clock = datetime.strptime(start_time_control.input_value(), "%I:%M %p").time()
                end_clock = datetime.strptime(end_time_control.input_value(), "%I:%M %p").time()
            except ValueError as exc:
                raise EventFormInvalid("TimeTree event times could not be parsed safely.") from exc
            start_at = datetime.combine(date.fromisoformat(start_date_value), start_clock, TOKYO)
            end_at = datetime.combine(date.fromisoformat(end_date_value), end_clock, TOKYO)
            end_exclusive = None
        note = self._read_note(page)
        description = _description_from_note(note, request.payload.ownership_marker)
        return TimeTreeEventPayload(
            organizer_event_id=request.organizer_event_id,
            ownership_marker=request.payload.ownership_marker,
            title=title.input_value(),
            description=description,
            start_at=_iso_utc(start_at),
            end_at=_iso_utc(end_at),
            all_day=is_all_day,
            start_date=start_date_value if is_all_day else None,
            end_date_exclusive=end_exclusive.isoformat() if is_all_day else None,
            location=location.input_value().strip() or None,
        )

    def _open_and_inspect(
        self,
        page: Any,
        request: TimeTreeOperationRequest,
        event_url: str,
        event_id: str,
        expected_payload: TimeTreeEventPayload,
    ) -> str:
        if derive_event_id(event_url) != event_id:
            raise OwnershipError("Event URL does not contain the exact expected event ID.")
        if not self.client._event_url_belongs_to_calendar(event_url, request.calendar.url):
            raise OwnershipError("Event URL does not belong to the expected calendar.")
        self.client._navigate(page, event_url, "inspect_production_event")
        if self.client._auth_required(page):
            raise AuthenticationRequired("TimeTree authentication expired.")
        self.client._wait_for_event_detail_title(
            page,
            expected_title=expected_payload.title,
            expected_event_id=event_id,
        )
        self.client._open_event_action(page, EDIT_NAMES, "inspect edit")
        observed = self._read_form_payload(page, request)
        return canonical_payload_hash(observed)

    def create(self, request: TimeTreeOperationRequest) -> BrowserResult:
        phase = "before_browser"
        write = SingleWriteAttempt()
        try:
            with self.client._session(f"production_create_{request.operation_id}") as (page, _):
                self.client._open_authenticated_home(page)
                calendar_id, calendar_url = self._verified_calendar(page, request)
                phase = "before_form"
                self.client._open_create_form(page)
                self._fill_form(page, request.payload)
                phase = "before_save"
                save = self.client._save_event_control(page)
                phase = "save_attempted"
                write.click(save)
                self.client._dismiss_release_announcement(page)
                event_url = self.client._resolve_exact_title_event_url(page, request.payload.title)
                event_id = derive_event_id(event_url)
                if not event_id:
                    raise OwnershipError("Created event did not resolve to one stable event ID.")
                observed_hash = self._open_and_inspect(page, request, event_url, event_id, request.payload)
                if observed_hash != request.desired_hash:
                    raise OwnershipError("Created event content did not match the exact desired payload.")
                return BrowserResult(event_id, event_url, calendar_id, calendar_url, observed_hash, write.count)
        except ProductionOperationError:
            raise
        except AuthenticationRequired as exc:
            raise ProductionOperationError(outcome="auth_required", phase=phase, code="auth_required", message=str(exc), write_count=write.count) from exc
        except SelectorNotFound as exc:
            raise ProductionOperationError(outcome="selector_error", phase=phase, code="selector_error", message=str(exc), write_count=write.count) from exc
        except Exception as exc:
            outcome = "reconcile_required" if phase == "save_attempted" else "retryable_error"
            raise ProductionOperationError(outcome=outcome, phase=phase, code="create_failed", message=f"{type(exc).__name__}: CREATE browser operation failed.", write_count=write.count) from exc

    def reconcile(self, request: TimeTreeOperationRequest) -> BrowserResult:
        try:
            with self.client._session(f"production_reconcile_{request.operation_id}") as (page, _):
                self.client._open_authenticated_home(page)
                calendar_id, calendar_url = self._verified_calendar(page, request)
                if request.action == "delete":
                    if not request.event_id or not request.event_url or not request.base_payload:
                        raise ProductionOperationError(
                            outcome="rejected", phase="before_browser", code="missing_remote_identity",
                            message="DELETE reconciliation requires the stored remote identity.",
                        )
                    self.client._navigate(page, request.event_url, "reconcile_production_delete")
                    # Absence is accepted only when TimeTree redirects away from the
                    # exact stored event route. A missing title on the same route is
                    # ambiguous (SPA delay/selector drift) and remains fail-closed.
                    if derive_event_id(page.url) == request.event_id:
                        raise ProductionOperationError(
                            outcome="reconcile_required", phase="before_save", code="delete_not_proven",
                            message="The stored TimeTree event URL still resolves; deletion is not proven.",
                        )
                    return BrowserResult(
                        request.event_id, request.event_url, calendar_id, calendar_url,
                        request.base_hash, 0,
                    )
                try:
                    event_url = self.client._search_exact_title_event_url(page, request.payload.title)
                except OwnershipError as exc:
                    if "did not appear" in str(exc) or "found 0" in str(exc):
                        raise ProductionOperationError(outcome="not_found", phase="before_save", code="event_not_found", message="No uniquely verifiable matching TimeTree event was found.") from exc
                    raise ProductionOperationError(outcome="conflict", phase="before_save", code="ambiguous_candidates", message=str(exc)) from exc
                event_id = derive_event_id(event_url)
                if not event_id:
                    raise OwnershipError("Reconciled event URL has no stable event ID.")
                observed_hash = self._open_and_inspect(page, request, event_url, event_id, request.payload)
                if observed_hash != request.desired_hash:
                    raise ProductionOperationError(outcome="conflict", phase="before_save", code="remote_payload_mismatch", message="The reconciled event does not exactly match the desired payload.")
                return BrowserResult(event_id, event_url, calendar_id, calendar_url, observed_hash, 0)
        except ProductionOperationError:
            raise
        except AuthenticationRequired as exc:
            raise ProductionOperationError(outcome="auth_required", phase="before_browser", code="auth_required", message=str(exc)) from exc
        except SelectorNotFound as exc:
            raise ProductionOperationError(outcome="selector_error", phase="before_save", code="selector_error", message=str(exc)) from exc
        except Exception as exc:
            raise ProductionOperationError(outcome="reconcile_required", phase="before_save", code="reconcile_failed", message=f"{type(exc).__name__}: reconciliation could not prove one result.") from exc

    def update(self, request: TimeTreeOperationRequest) -> BrowserResult:
        if not request.event_id or not request.event_url or not request.base_hash or not request.base_payload:
            raise ProductionOperationError(outcome="rejected", phase="before_browser", code="missing_remote_identity", message="UPDATE requires event identity and base hash.")
        write = SingleWriteAttempt()
        phase = "before_browser"
        try:
            with self.client._session(f"production_update_{request.operation_id}") as (page, _):
                self.client._open_authenticated_home(page)
                calendar_id, calendar_url = self._verified_calendar(page, request)
                remote_hash = self._open_and_inspect(
                    page, request, request.event_url, request.event_id, request.base_payload
                )
                if remote_hash != request.base_hash:
                    raise ProductionOperationError(outcome="conflict", phase="before_save", code="remote_changed", message="TimeTree event changed since the last verified sync.")
                phase = "before_form"
                self._fill_form(page, request.payload, expected_title=request.base_payload.title)
                phase = "before_save"
                save = self.client._save_event_control(page)
                phase = "save_attempted"
                write.click(save)
                observed_hash = self._open_and_inspect(
                    page, request, request.event_url, request.event_id, request.payload
                )
                if observed_hash != request.desired_hash:
                    raise OwnershipError("Updated event did not match the exact desired payload.")
                return BrowserResult(request.event_id, request.event_url, calendar_id, calendar_url, observed_hash, write.count)
        except ProductionOperationError:
            raise
        except AuthenticationRequired as exc:
            raise ProductionOperationError(outcome="auth_required", phase=phase, code="auth_required", message=str(exc), write_count=write.count) from exc
        except SelectorNotFound as exc:
            raise ProductionOperationError(outcome="selector_error", phase=phase, code="selector_error", message=str(exc), write_count=write.count) from exc
        except Exception as exc:
            outcome = "reconcile_required" if phase == "save_attempted" else "retryable_error"
            raise ProductionOperationError(outcome=outcome, phase=phase, code="update_failed", message=f"{type(exc).__name__}: UPDATE browser operation failed.", write_count=write.count) from exc

    def delete(self, request: TimeTreeOperationRequest) -> BrowserResult:
        if not request.event_id or not request.event_url or not request.base_payload:
            raise ProductionOperationError(outcome="rejected", phase="before_browser", code="missing_remote_identity", message="DELETE requires event identity.")
        write = SingleWriteAttempt()
        phase = "before_browser"
        try:
            with self.client._session(f"production_delete_{request.operation_id}") as (page, _):
                self.client._open_authenticated_home(page)
                calendar_id, calendar_url = self._verified_calendar(page, request)
                remote_hash = self._open_and_inspect(
                    page, request, request.event_url, request.event_id, request.base_payload
                )
                if request.base_hash and remote_hash != request.base_hash:
                    raise ProductionOperationError(outcome="conflict", phase="before_save", code="remote_changed", message="TimeTree event changed since the last verified sync.")
                self.client._navigate(page, request.event_url, "delete_production_event")
                self.client._wait_for_event_detail_title(
                    page,
                    expected_title=request.base_payload.title,
                    expected_event_id=request.event_id,
                )
                self.client._open_event_action(page, DELETE_NAMES, "delete")
                confirm = unique_role_locator(page, "button", CONFIRM_DELETE_NAMES, "delete confirmation button")
                if confirm is None:
                    raise SelectorNotFound("Could not uniquely identify the delete confirmation control.")
                phase = "before_save"
                phase = "save_attempted"
                write.click(confirm)
                self.client._navigate(page, request.event_url, "verify_production_delete")
                if derive_event_id(page.url) == request.event_id:
                    raise OwnershipError("Deleted event URL still resolves to the exact stored event ID.")
                return BrowserResult(request.event_id, request.event_url, calendar_id, calendar_url, remote_hash, write.count)
        except ProductionOperationError:
            raise
        except AuthenticationRequired as exc:
            raise ProductionOperationError(outcome="auth_required", phase=phase, code="auth_required", message=str(exc), write_count=write.count) from exc
        except SelectorNotFound as exc:
            raise ProductionOperationError(outcome="selector_error", phase=phase, code="selector_error", message=str(exc), write_count=write.count) from exc
        except Exception as exc:
            outcome = "reconcile_required" if phase == "save_attempted" else "retryable_error"
            raise ProductionOperationError(outcome=outcome, phase=phase, code="delete_failed", message=f"{type(exc).__name__}: DELETE browser operation failed.", write_count=write.count) from exc
