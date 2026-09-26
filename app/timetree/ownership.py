from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.timetree.models import (
    POC_TITLE_PREFIX,
    POC_TOKEN_PREFIX,
    OwnedEventRecord,
    TestEventSpec,
    utc_now_iso,
)


class OwnershipError(RuntimeError):
    """Raised when an operation cannot prove ownership of a TimeTree event."""


def build_test_event(event_date: date, custom_title: str | None = None) -> TestEventSpec:
    token = f"{POC_TOKEN_PREFIX}{uuid.uuid4()}"
    label = (custom_title or "TimeTree Sync Test").strip()
    if label.startswith(POC_TITLE_PREFIX):
        label = label.removeprefix(POC_TITLE_PREFIX).strip()
    title = f"{POC_TITLE_PREFIX} {label} [{token}]"
    description = (
        "Created by the home-server TimeTree Playwright PoC. "
        f"Ownership token: {token}. Safe to modify only through the matching local PoC record."
    )
    return TestEventSpec(
        title=title,
        event_date=event_date,
        ownership_token=token,
        description=description,
    )


def build_updated_title(record: OwnedEventRecord, label: str | None = None) -> str:
    next_label = (label or "TimeTree Sync Test (updated)").strip()
    if next_label.startswith(POC_TITLE_PREFIX):
        next_label = next_label.removeprefix(POC_TITLE_PREFIX).strip()
    return f"{POC_TITLE_PREFIX} {next_label} [{record.ownership_token}]"


def derive_event_id(event_url: str) -> str | None:
    parsed = urlparse(event_url)
    match = re.fullmatch(
        r"/calendars/[^/]+/events/([^/]+)/?",
        parsed.path,
        re.IGNORECASE,
    )
    return unquote(match.group(1)) if match else None


def assert_safe_event_url(event_url: str, event_id: str | None = None) -> str:
    parsed = urlparse(event_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "timetreeapp.com"
        or parsed.netloc != "timetreeapp.com"
        or parsed.username
        or parsed.password
    ):
        raise OwnershipError("Event URL is not an HTTPS timetreeapp.com URL.")
    derived = derive_event_id(event_url)
    if not derived:
        raise OwnershipError("A stable TimeTree event ID could not be derived from the event URL.")
    if event_id and derived != event_id:
        raise OwnershipError("Stored event ID does not match the event URL.")
    return derived


def assert_record_owned(record: OwnedEventRecord) -> None:
    if record.status != "active":
        raise OwnershipError(f"Record {record.record_id} is not active.")
    if not record.current_title.startswith(f"{POC_TITLE_PREFIX} "):
        raise OwnershipError("Stored title is missing the PoC prefix.")
    if not record.ownership_token.startswith(POC_TOKEN_PREFIX):
        raise OwnershipError("Stored ownership token is invalid.")
    if f"[{record.ownership_token}]" not in record.current_title:
        raise OwnershipError("Stored title does not contain the ownership token.")
    assert_safe_event_url(record.event_url, record.event_id)


def assert_owned_page(record: OwnedEventRecord, current_url: str, visible_text: str) -> None:
    assert_record_owned(record)
    current_id = assert_safe_event_url(current_url)
    if current_id != record.event_id:
        raise OwnershipError("Current page event ID does not match the owned record.")
    if record.current_title not in visible_text:
        raise OwnershipError("The exact stored PoC title is not visible on the event page.")
    if record.ownership_token not in visible_text:
        raise OwnershipError("The ownership token is not visible on the event page.")


class OwnershipRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self, *, active_only: bool = False) -> list[OwnedEventRecord]:
        records = [OwnedEventRecord.from_dict(item) for item in self._load()["events"]]
        if active_only:
            records = [record for record in records if record.status == "active"]
        return records

    def list_pending_creates(self) -> list[dict]:
        return self._load_pending()["events"]

    def record_pending_create(self, *, spec: TestEventSpec, calendar_name: str) -> None:
        payload = self._load_pending()
        payload["events"] = [
            item for item in payload["events"] if item["ownership_token"] != spec.ownership_token
        ]
        payload["events"].append(
            {
                "ownership_token": spec.ownership_token,
                "calendar_name": calendar_name,
                "title": spec.title,
                "event_date": spec.event_date.isoformat(),
                "recorded_at": utc_now_iso(),
                "status": "save-attempted",
            }
        )
        self._save_pending(payload)

    def clear_pending_create(self, ownership_token: str) -> None:
        payload = self._load_pending()
        payload["events"] = [
            item for item in payload["events"] if item["ownership_token"] != ownership_token
        ]
        self._save_pending(payload)

    def get(self, record_id: str | None = None) -> OwnedEventRecord:
        records = self.list(active_only=True)
        if record_id:
            matches = [record for record in records if record.record_id == record_id]
            if len(matches) != 1:
                raise OwnershipError(f"No active owned event record found for {record_id}.")
            return matches[0]
        if len(records) != 1:
            raise OwnershipError(
                "Specify --record-id because the number of active owned event records is not exactly one."
            )
        return records[0]

    def add(
        self,
        *,
        spec: TestEventSpec,
        calendar_name: str,
        event_url: str,
    ) -> OwnedEventRecord:
        event_id = assert_safe_event_url(event_url)
        now = utc_now_iso()
        record = OwnedEventRecord(
            record_id=str(uuid.uuid4()),
            ownership_token=spec.ownership_token,
            calendar_name=calendar_name,
            current_title=spec.title,
            event_date=spec.event_date.isoformat(),
            event_url=event_url,
            event_id=event_id,
            created_at=now,
            updated_at=now,
        )
        assert_record_owned(record)
        payload = self._load()
        payload["events"].append(record.to_dict())
        self._save(payload)
        return record

    def update_title(self, record_id: str, title: str) -> OwnedEventRecord:
        payload = self._load()
        record = self._find(payload, record_id)
        if f"[{record.ownership_token}]" not in title or not title.startswith(POC_TITLE_PREFIX):
            raise OwnershipError("Updated title must retain both the PoC prefix and ownership token.")
        record.current_title = title
        record.updated_at = utc_now_iso()
        self._replace(payload, record)
        self._save(payload)
        return record

    def mark_deleted(self, record_id: str) -> OwnedEventRecord:
        payload = self._load()
        record = self._find(payload, record_id)
        assert_record_owned(record)
        record.status = "deleted"
        record.updated_at = utc_now_iso()
        self._replace(payload, record)
        self._save(payload)
        return record

    def _find(self, payload: dict, record_id: str) -> OwnedEventRecord:
        for item in payload["events"]:
            if item["record_id"] == record_id:
                return OwnedEventRecord.from_dict(item)
        raise OwnershipError(f"Owned event record not found: {record_id}")

    @staticmethod
    def _replace(payload: dict, record: OwnedEventRecord) -> None:
        payload["events"] = [
            record.to_dict() if item["record_id"] == record.record_id else item
            for item in payload["events"]
        ]

    def _load(self) -> dict:
        if not self.path.exists():
            return {"version": 1, "events": []}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("events"), list):
            raise OwnershipError(f"Invalid ownership registry: {self.path}")
        return value

    def _save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.path)
        self.path.chmod(0o600)

    @property
    def pending_path(self) -> Path:
        return self.path.with_name("pending-creates.json")

    def _load_pending(self) -> dict:
        if not self.pending_path.exists():
            return {"version": 1, "events": []}
        value = json.loads(self.pending_path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("events"), list):
            raise OwnershipError(f"Invalid pending-create registry: {self.pending_path}")
        return value

    def _save_pending(self, payload: dict) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.pending_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, self.pending_path)
        self.pending_path.chmod(0o600)
