from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.timetree_routes import get_timetree_production_adapter
from app.main import app
from app.timetree.config import TimeTreeConfig
from app.timetree.models import CalendarInfo
from app.timetree.production_adapter import TimeTreeProductionAdapter


class FakeAdapter:
    def status(self) -> dict[str, object]:
        return {
            "authenticated": True,
            "storage_state_exists": True,
            "calendar_configured": True,
            "calendar_found": True,
            "calendar_name": "Partner",
            "calendar_url": "https://timetreeapp.com/calendars/example",
            "ready": True,
            "adapter_write_count": 0,
        }


def test_status_fails_closed_when_token_is_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("TIMETREE_INTERNAL_API_TOKEN", raising=False)
    with TestClient(app) as client:
        assert client.get("/internal/timetree/v1/status").status_code == 503


def test_status_rejects_missing_or_wrong_bearer_token(monkeypatch) -> None:
    monkeypatch.setenv("TIMETREE_INTERNAL_API_TOKEN", "secret-token")
    with TestClient(app) as client:
        assert client.get("/internal/timetree/v1/status").status_code == 401
        assert client.get("/internal/timetree/v1/status", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_status_is_read_only_and_redacts_credentials(monkeypatch) -> None:
    monkeypatch.setenv("TIMETREE_INTERNAL_API_TOKEN", "secret-token")
    app.dependency_overrides[get_timetree_production_adapter] = FakeAdapter
    try:
        with TestClient(app) as client:
            response = client.get(
                "/internal/timetree/v1/status",
                headers={"Authorization": "Bearer secret-token"},
            )
        assert response.status_code == 200
        assert response.json()["adapter_write_count"] == 0
        assert "secret-token" not in response.text
    finally:
        app.dependency_overrides.pop(get_timetree_production_adapter, None)


class FakeBrowserClient:
    def __init__(self, calendars: list[CalendarInfo]) -> None:
        self.calendars = calendars
        self.check_auth_calls = 0
        self.list_calls = 0

    def check_auth(self) -> dict[str, object]:
        self.check_auth_calls += 1
        return {"authenticated": True, "storage_state_exists": True}

    def list_calendars(self) -> list[CalendarInfo]:
        self.list_calls += 1
        return self.calendars


def test_production_status_requires_one_exact_calendar(tmp_path) -> None:
    config = TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner")
    exact = FakeBrowserClient([CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/one")])
    ready = TimeTreeProductionAdapter(config, client_factory=lambda _: exact).status()
    assert ready["ready"] is True
    assert ready["adapter_write_count"] == 0

    duplicates = FakeBrowserClient([
        CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/one"),
        CalendarInfo(name="Partner", url="https://timetreeapp.com/calendars/two"),
    ])
    ambiguous = TimeTreeProductionAdapter(config, client_factory=lambda _: duplicates).status()
    assert ambiguous["ready"] is False
    assert ambiguous["calendar_found"] is False
