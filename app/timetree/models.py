from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any

POC_TITLE_PREFIX = "[HOME-SERVER-POC]"
POC_TOKEN_PREFIX = "HSP-"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class CalendarInfo:
    name: str
    url: str | None


@dataclass(frozen=True)
class TestEventSpec:
    title: str
    event_date: date
    ownership_token: str
    description: str


@dataclass
class OwnedEventRecord:
    record_id: str
    ownership_token: str
    calendar_name: str
    current_title: str
    event_date: str
    event_url: str
    event_id: str
    created_at: str
    updated_at: str
    status: str = "active"
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> OwnedEventRecord:
        return cls(**value)
