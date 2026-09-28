from __future__ import annotations

from datetime import date
import json

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


def _record_pending(registry: OwnershipRegistry, token: str, title: str) -> None:
    payload = {
        "version": 1,
        "events": [
            {
                "ownership_token": token,
                "calendar_name": "Partner",
                "title": title,
                "event_date": "2026-09-28",
                "recorded_at": "2026-09-27T00:00:00+00:00",
                "status": "save-attempted",
            }
        ],
    }
    registry.pending_path.write_text(json.dumps(payload), encoding="utf-8")


def test_pending_lookup_requires_exactly_one_record(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-11111111-1111-1111-1111-111111111111"

    with pytest.raises(OwnershipError, match="found 0"):
        registry.get_pending_create(token)

    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{token}]")
    payload = json.loads(registry.pending_path.read_text(encoding="utf-8"))
    payload["events"].append(dict(payload["events"][0]))
    registry.pending_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(OwnershipError, match="found 2"):
        registry.get_pending_create(token)


def test_pending_lookup_rejects_title_with_different_token(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-11111111-1111-1111-1111-111111111111"
    other = "HSP-22222222-2222-2222-2222-222222222222"
    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{other}]")

    with pytest.raises(OwnershipError, match="exact ownership token"):
        registry.get_pending_create(token)


def test_pending_promotion_is_atomic_and_clears_only_verified_pending(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 29))
    registry.record_pending_create(spec=spec, calendar_name="Partner")

    record = registry.promote_pending_create(spec.ownership_token, event_url=EVENT_URL)

    assert record.current_title == spec.title
    assert registry.list() == [record]
    assert registry.list_pending_creates() == []


def test_pending_promotion_failure_rolls_back_owned_and_keeps_pending(
    tmp_path,
    monkeypatch,
) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    spec = build_test_event(date(2026, 9, 29))
    registry.record_pending_create(spec=spec, calendar_name="Partner")
    monkeypatch.setattr(
        registry,
        "_save_pending",
        lambda payload: (_ for _ in ()).throw(OSError("simulated pending write failure")),
    )

    with pytest.raises(OSError, match="simulated"):
        registry.promote_pending_create(spec.ownership_token, event_url=EVENT_URL)

    assert registry.list() == []
    assert len(registry.list_pending_creates()) == 1


def test_pending_cleanup_dry_run_does_not_change_file(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-11111111-1111-1111-1111-111111111111"
    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{token}]")
    before = registry.pending_path.read_bytes()

    result = registry.cleanup_pending_create(token, dry_run=True)

    assert result["dry_run"] is True
    assert result["ownership_token"] == token
    assert result["title"] == f"[HOME-SERVER-POC] Test [{token}]"
    assert result["event_date"] == "2026-09-28"
    assert result["current_status"] == "save-attempted"
    assert result["action"] == "remove_pending_ledger_record"
    assert result["pending_count_before"] == 1
    assert result["pending_count_after"] == 0
    assert registry.pending_path.read_bytes() == before


def test_pending_cleanup_apply_removes_only_exact_token_and_preserves_owned_file(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    first = build_test_event(date(2026, 9, 28))
    second = build_test_event(date(2026, 9, 28))
    registry.record_pending_create(spec=first, calendar_name="Partner")
    registry.record_pending_create(spec=second, calendar_name="Partner")
    owned = registry.add(spec=first, calendar_name="Partner", event_url=EVENT_URL)
    owned_before = registry.path.read_bytes()

    result = registry.cleanup_pending_create(first.ownership_token, dry_run=False)

    assert result["dry_run"] is False
    assert result["pending_count_before"] == 2
    assert result["pending_count_after"] == 1
    assert [item["ownership_token"] for item in registry.list_pending_creates()] == [
        second.ownership_token
    ]
    assert registry.path.read_bytes() == owned_before
    assert registry.get(owned.record_id).event_id == owned.event_id


def test_pending_cleanup_missing_token_fails_closed_without_write(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    existing = build_test_event(date(2026, 9, 28))
    registry.record_pending_create(spec=existing, calendar_name="Partner")
    before = registry.pending_path.read_bytes()

    with pytest.raises(OwnershipError, match="found 0"):
        registry.cleanup_pending_create(
            "HSP-22222222-2222-2222-2222-222222222222",
            dry_run=False,
        )

    assert registry.pending_path.read_bytes() == before


def test_pending_cleanup_duplicate_token_fails_closed_without_write(tmp_path) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-33333333-3333-3333-3333-333333333333"
    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{token}]")
    payload = json.loads(registry.pending_path.read_text(encoding="utf-8"))
    payload["events"].append(dict(payload["events"][0]))
    registry.pending_path.write_text(json.dumps(payload), encoding="utf-8")
    before = registry.pending_path.read_bytes()

    with pytest.raises(OwnershipError, match="found 2"):
        registry.cleanup_pending_create(token, dry_run=False)

    assert registry.pending_path.read_bytes() == before


def test_pending_cleanup_apply_uses_atomic_replace(tmp_path, monkeypatch) -> None:
    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-44444444-4444-4444-4444-444444444444"
    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{token}]")
    replacements: list[tuple] = []
    from app.timetree import ownership as ownership_module

    original_replace = ownership_module.os.replace

    def observed_replace(source, destination) -> None:
        replacements.append((source, destination))
        original_replace(source, destination)

    monkeypatch.setattr(ownership_module.os, "replace", observed_replace)

    registry.cleanup_pending_create(token, dry_run=False)

    assert replacements == [(registry.pending_path.with_suffix(".tmp"), registry.pending_path)]
    assert registry.pending_path.stat().st_mode & 0o777 == 0o600


def test_pending_cleanup_cli_does_not_construct_timetree_client_or_playwright(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from app.timetree import __main__ as cli

    registry = OwnershipRegistry(tmp_path / "owned-events.json")
    token = "HSP-55555555-5555-5555-5555-555555555555"
    _record_pending(registry, token, f"[HOME-SERVER-POC] Test [{token}]")

    def forbidden_client(*args, **kwargs):
        raise AssertionError("pending-cleanup must not construct TimeTreeClient")

    monkeypatch.setattr(cli, "TimeTreeClient", forbidden_client)

    exit_code = cli.main(
        [
            "--data-dir",
            str(tmp_path),
            "pending-cleanup",
            "--ownership-token",
            token,
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["dry_run"] is True
    assert registry.list_pending_creates()[0]["ownership_token"] == token


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
