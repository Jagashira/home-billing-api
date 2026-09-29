from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.timetree.client import TimeTreeClient
from app.timetree.config import TimeTreeConfig


class TimeTreeProductionAdapter:
    """Read-only production boundary for the TimeTree browser adapter."""

    def __init__(
        self,
        config: TimeTreeConfig | None = None,
        client_factory: Callable[[TimeTreeConfig], TimeTreeClient] = TimeTreeClient,
    ) -> None:
        self.config = config or TimeTreeConfig.from_env()
        self.client_factory = client_factory

    def status(self) -> dict[str, Any]:
        client = self.client_factory(self.config)
        auth = client.check_auth()
        authenticated = bool(auth.get("authenticated"))
        configured = bool(self.config.calendar_name)
        calendar_name: str | None = None
        calendar_url: str | None = None
        found = False
        if authenticated and configured:
            matches = [item for item in client.list_calendars() if item.name == self.config.calendar_name]
            if len(matches) == 1:
                found = True
                calendar_name = matches[0].name
                calendar_url = matches[0].url
        return {
            "authenticated": authenticated,
            "storage_state_exists": bool(auth.get("storage_state_exists")),
            "calendar_configured": configured,
            "calendar_found": found,
            "calendar_name": calendar_name,
            "calendar_url": calendar_url,
            "ready": authenticated and configured and found,
            "adapter_write_count": 0,
        }
