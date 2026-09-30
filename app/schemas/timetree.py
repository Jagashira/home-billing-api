from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TimeTreeAdapterStatusRead(BaseModel):
    authenticated: bool
    storage_state_exists: bool
    calendar_configured: bool
    calendar_found: bool
    calendar_name: str | None
    calendar_id: str | None = None
    calendar_url: str | None
    ready: bool
    adapter_write_count: int = 0


class TimeTreeCalendarIdentity(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    calendar_id: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2000)


class TimeTreeEventPayload(BaseModel):
    organizer_event_id: str = Field(min_length=1, max_length=500)
    ownership_marker: str = Field(min_length=1, max_length=1000)
    title: str = Field(min_length=1, max_length=1000)
    description: str | None = Field(default=None, max_length=10_000)
    start_at: str
    end_at: str
    all_day: bool
    start_date: str | None = None
    end_date_exclusive: str | None = None
    location: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_marker_and_dates(self) -> TimeTreeEventPayload:
        expected = f"HOME_DASHBOARD_EVENT_ID:{self.organizer_event_id}"
        if self.ownership_marker != expected:
            raise ValueError("ownership_marker does not exactly match organizer_event_id")
        if self.description and "HOME_DASHBOARD_EVENT_ID:" in self.description:
            raise ValueError("description must not contain a production ownership marker")
        if self.all_day and (not self.start_date or not self.end_date_exclusive):
            raise ValueError("all-day events require start_date and end_date_exclusive")
        return self


class TimeTreeOperationRequest(BaseModel):
    action: Literal["create", "update", "delete"]
    operation_id: str = Field(min_length=1, max_length=500)
    organizer_event_id: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=1000)
    calendar: TimeTreeCalendarIdentity
    payload: TimeTreeEventPayload
    base_payload: TimeTreeEventPayload | None = None
    desired_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_id: str | None = Field(default=None, max_length=500)
    event_url: str | None = Field(default=None, max_length=2000)
    base_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_identity(self) -> TimeTreeOperationRequest:
        if self.payload.organizer_event_id != self.organizer_event_id:
            raise ValueError("payload organizer_event_id mismatch")
        expected_key = f"{self.organizer_event_id}:{self.action}:{self.desired_hash}"
        if self.idempotency_key != expected_key:
            raise ValueError("idempotency_key does not match organizer event, action, and desired hash")
        if (self.event_id is None) != (self.event_url is None):
            raise ValueError("event_id and event_url must be supplied together")
        if self.action in {"update", "delete"}:
            if not self.event_id or not self.base_payload or not self.base_hash:
                raise ValueError(f"{self.action} requires event identity, base_payload, and base_hash")
            if self.base_payload.organizer_event_id != self.organizer_event_id:
                raise ValueError("base_payload organizer_event_id mismatch")
        return self


class TimeTreeOperationResponse(BaseModel):
    outcome: Literal[
        "verified",
        "reconcile_required",
        "retryable_error",
        "auth_required",
        "selector_error",
        "conflict",
        "not_found",
        "rejected",
    ]
    phase: Literal[
        "before_browser",
        "before_form",
        "before_save",
        "save_attempted",
        "remote_verified",
    ]
    operation_id: str
    organizer_event_id: str
    event_id: str | None = None
    event_url: str | None = None
    calendar_id: str | None = None
    calendar_url: str | None = None
    observed_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    artifact_ref: str | None = None
    adapter_write_count: int = 0
