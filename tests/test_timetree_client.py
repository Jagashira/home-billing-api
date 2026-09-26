from __future__ import annotations

import json

from app.timetree.client import TimeTreeClient
from app.timetree.config import TimeTreeConfig


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
