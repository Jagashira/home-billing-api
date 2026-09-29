from __future__ import annotations

from pydantic import BaseModel


class TimeTreeAdapterStatusRead(BaseModel):
    authenticated: bool
    storage_state_exists: bool
    calendar_configured: bool
    calendar_found: bool
    calendar_name: str | None
    calendar_url: str | None
    ready: bool
    adapter_write_count: int = 0
