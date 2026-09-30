from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.schemas.timetree import TimeTreeEventPayload, TimeTreeOperationRequest


Outcome = Literal[
    "verified", "reconcile_required", "retryable_error", "auth_required",
    "selector_error", "conflict", "not_found", "rejected",
]
Phase = Literal["before_browser", "before_form", "before_save", "save_attempted", "remote_verified"]


def canonical_payload_dict(payload: TimeTreeEventPayload) -> dict[str, object]:
    return {
        "allDay": payload.all_day,
        "description": payload.description,
        "endAt": payload.end_at,
        "endDateExclusive": payload.end_date_exclusive,
        "location": payload.location,
        "organizerEventId": payload.organizer_event_id,
        "ownershipMarker": payload.ownership_marker,
        "startAt": payload.start_at,
        "startDate": payload.start_date,
        "title": payload.title,
    }


def canonical_payload_hash(payload: TimeTreeEventPayload) -> str:
    encoded = json.dumps(
        canonical_payload_dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calendar_id_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.netloc != "timetreeapp.com":
        return None
    if len(parts) != 2 or parts[0] != "calendars" or not parts[1]:
        return None
    return parts[1]


def canonical_calendar_url(calendar_id: str) -> str:
    return f"https://timetreeapp.com/calendars/{calendar_id}"


def validate_request_hash(request: TimeTreeOperationRequest) -> None:
    if canonical_payload_hash(request.payload) != request.desired_hash:
        raise ValueError("desired_hash does not match the canonical payload")
    if request.base_payload and canonical_payload_hash(request.base_payload) != request.base_hash:
        raise ValueError("base_hash does not match the canonical base payload")


@dataclass(frozen=True)
class BrowserResult:
    event_id: str | None
    event_url: str | None
    calendar_id: str
    calendar_url: str
    observed_hash: str | None
    write_count: int


class ProductionOperationError(RuntimeError):
    def __init__(
        self,
        *,
        outcome: Outcome,
        phase: Phase,
        code: str,
        message: str,
        write_count: int = 0,
    ) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.phase = phase
        self.code = code
        self.safe_message = message
        self.write_count = write_count
