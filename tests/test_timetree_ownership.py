from __future__ import annotations

from datetime import date

import pytest

from app.timetree.config import TimeTreeConfig
from app.timetree.ownership import (
    OwnershipError,
    OwnershipRegistry,
    assert_owned_page,
    build_test_event,
    build_updated_title,
    derive_event_id,
)

EVENT_URL = "https://timetreeapp.com/calendars/calendar-1/events/event-123"


def test_registry_records_unique_token_and_stable_event_id(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))

    record = registry.add(spec=spec, calendar_name="Partner", event_url=EVENT_URL)

    assert record.event_id == "event-123"
    assert record.ownership_token in record.current_title
    assert registry.get(record.record_id).event_url == EVENT_URL
    assert (tmp_path / "owned-events.json").stat().st_mode & 0o777 == 0o600


def test_update_title_cannot_drop_ownership_token(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))
    record = registry.add(spec=spec, calendar_name="Partner", event_url=EVENT_URL)

    with pytest.raises(OwnershipError):
        registry.update_title(record.record_id, "ordinary event")

    updated = build_updated_title(record, "Safe updated event")
    assert registry.update_title(record.record_id, updated).ownership_token in updated


def test_pending_create_survives_until_stable_record_is_saved(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))

    registry.record_pending_create(spec=spec, calendar_name="Partner")
    assert registry.list_pending_creates()[0]["ownership_token"] == spec.ownership_token

    registry.add(spec=spec, calendar_name="Partner", event_url=EVENT_URL)
    registry.clear_pending_create(spec.ownership_token)
    assert registry.list_pending_creates() == []


def test_owned_page_requires_url_title_and_token_match(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))
    record = registry.add(spec=spec, calendar_name="Partner", event_url=EVENT_URL)

    assert_owned_page(record, EVENT_URL, f"Partner\n{record.current_title}\n{record.ownership_token}")

    with pytest.raises(OwnershipError):
        assert_owned_page(
            record,
            "https://timetreeapp.com/calendars/calendar-1/events/different",
            record.current_title,
        )
    with pytest.raises(OwnershipError):
        assert_owned_page(record, EVENT_URL, "some existing event")


def test_event_url_must_be_real_timetree_event_route(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))

    with pytest.raises(OwnershipError):
        registry.add(
            spec=spec,
            calendar_name="Partner",
            event_url="https://example.com/calendars/calendar-1/events/event-123",
        )
    with pytest.raises(OwnershipError):
        registry.add(
            spec=spec,
            calendar_name="Partner",
            event_url="https://timetreeapp.com/calendars/calendar-1",
        )


def test_derive_event_id_only_accepts_observed_event_detail_route() -> None:
    assert derive_event_id(EVENT_URL) == "event-123"
    assert derive_event_id(f"{EVENT_URL}?date=2026-09-23") == "event-123"
    assert derive_event_id("https://timetreeapp.com/calendar?event_id=abc") is None
    assert derive_event_id(f"{EVENT_URL}/edit") is None
    assert derive_event_id("https://timetreeapp.com/plans/event-123") is None


def test_event_url_rejects_credentials_and_non_default_port(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 23))

    for unsafe_url in (
        "https://user@timetreeapp.com/calendars/calendar-1/events/event-123",
        "https://timetreeapp.com:443/calendars/calendar-1/events/event-123",
    ):
        with pytest.raises(OwnershipError):
            registry.add(spec=spec, calendar_name="Partner", event_url=unsafe_url)


def test_config_refuses_non_timetree_origin(tmp_path) -> None:
    with pytest.raises(ValueError):
        TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner", base_url="https://example.com")

    with pytest.raises(ValueError):
        TimeTreeConfig(
            data_dir=tmp_path,
            calendar_name="Partner",
            base_url="https://timetreeapp.com/intl/ja",
        )
