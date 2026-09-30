from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.timetree_routes import get_timetree_production_adapter
from app.main import app
from app.timetree.config import TimeTreeConfig
from app.timetree.models import CalendarInfo
from app.timetree.production_adapter import TimeTreeProductionAdapter
from app.timetree.production_models import BrowserResult, ProductionOperationError, canonical_payload_hash
from app.timetree.production_browser import SingleWriteAttempt, _description_from_note, _note_for
from app.timetree.ownership import OwnershipError
from app.schemas.timetree import TimeTreeEventPayload, TimeTreeOperationRequest


class FakeAdapter:
    def status(self) -> dict[str, object]:
        return {
            "authenticated": True,
            "storage_state_exists": True,
            "calendar_configured": True,
            "calendar_found": True,
            "calendar_name": "Partner",
            "calendar_id": "example",
            "calendar_url": "https://timetreeapp.com/calendars/example",
            "ready": True,
            "adapter_write_count": 0,
        }

    def create(self, request):
        return _verified_response(request)

    def reconcile(self, request):
        return _verified_response(request, writes=0)

    update = create
    delete = create


def _request() -> TimeTreeOperationRequest:
    payload = TimeTreeEventPayload.model_validate({
        "organizer_event_id": "event-1",
        "ownership_marker": "HOME_DASHBOARD_EVENT_ID:event-1",
        "title": "Dinner",
        "description": None,
        "start_at": "2026-10-01T10:00:00.000Z",
        "end_at": "2026-10-01T11:00:00.000Z",
        "all_day": False,
        "start_date": None,
        "end_date_exclusive": None,
        "location": None,
    })
    desired_hash = canonical_payload_hash(payload)
    body = {
        "action": "create",
        "operation_id": "op-1",
        "organizer_event_id": "event-1",
        "idempotency_key": f"event-1:create:{desired_hash}",
        "calendar": {"name": "Partner", "calendar_id": "example", "url": "https://timetreeapp.com/calendars/example"},
        "payload": payload.model_dump(),
        "desired_hash": desired_hash,
    }
    return TimeTreeOperationRequest.model_validate(body)


def _verified_response(request, writes=1):
    from app.schemas.timetree import TimeTreeOperationResponse
    return TimeTreeOperationResponse(
        outcome="verified", phase="remote_verified", operation_id=request.operation_id,
        organizer_event_id=request.organizer_event_id, event_id="remote-1",
        event_url="https://timetreeapp.com/calendars/example/events/remote-1",
        calendar_id="example", calendar_url="https://timetreeapp.com/calendars/example",
        observed_hash=request.desired_hash, adapter_write_count=writes,
    )


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


def test_write_endpoint_requires_both_adapter_gate_and_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("TIMETREE_INTERNAL_API_TOKEN", "secret-token")
    monkeypatch.delenv("TIMETREE_ADAPTER_WRITES_ENABLED", raising=False)
    app.dependency_overrides[get_timetree_production_adapter] = FakeAdapter
    try:
        with TestClient(app) as client:
            url = "/internal/timetree/v1/events/create"
            headers = {"Authorization": "Bearer secret-token"}
            assert client.post(url, headers=headers, json=_request().model_dump()).status_code == 503
            monkeypatch.setenv("TIMETREE_ADAPTER_WRITES_ENABLED", "true")
            assert client.post(url, headers=headers, json=_request().model_dump()).status_code == 403
            headers["X-TimeTree-Write-Confirmation"] = "WRITE_TIMETREE"
            response = client.post(url, headers=headers, json=_request().model_dump())
            assert response.status_code == 200
            assert response.json()["adapter_write_count"] == 1
    finally:
        app.dependency_overrides.pop(get_timetree_production_adapter, None)


def test_reconcile_is_read_only_and_does_not_require_write_gate(monkeypatch) -> None:
    monkeypatch.setenv("TIMETREE_INTERNAL_API_TOKEN", "secret-token")
    monkeypatch.delenv("TIMETREE_ADAPTER_WRITES_ENABLED", raising=False)
    app.dependency_overrides[get_timetree_production_adapter] = FakeAdapter
    try:
        with TestClient(app) as client:
            response = client.post(
                "/internal/timetree/v1/events/reconcile",
                headers={"Authorization": "Bearer secret-token"},
                json=_request().model_dump(),
            )
        assert response.status_code == 200
        assert response.json()["adapter_write_count"] == 0
    finally:
        app.dependency_overrides.pop(get_timetree_production_adapter, None)


class FakeBackend:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def create(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_adapter_validates_hash_before_browser_and_maps_uncertain_create(tmp_path) -> None:
    config = TimeTreeConfig(data_dir=tmp_path, calendar_name="Partner")
    backend = FakeBackend(result=BrowserResult("remote-1", "https://timetreeapp.com/calendars/example/events/remote-1", "example", "https://timetreeapp.com/calendars/example", _request().desired_hash, 1))
    adapter = TimeTreeProductionAdapter(config, client_factory=lambda _: object(), backend_factory=lambda _: backend)
    response = adapter.create(_request())
    assert response.outcome == "verified"
    assert backend.calls == 1

    invalid = _request().model_copy(update={"desired_hash": "a" * 64})
    rejected = adapter.create(invalid)
    assert rejected.outcome == "rejected"
    assert backend.calls == 1

    uncertain_backend = FakeBackend(error=ProductionOperationError(
        outcome="reconcile_required", phase="save_attempted", code="create_failed",
        message="post-save resolution failed", write_count=1,
    ))
    uncertain_adapter = TimeTreeProductionAdapter(config, client_factory=lambda _: object(), backend_factory=lambda _: uncertain_backend)
    uncertain = uncertain_adapter.create(_request())
    assert uncertain.outcome == "reconcile_required"
    assert uncertain.phase == "save_attempted"
    assert uncertain.adapter_write_count == 1


def test_production_note_marker_is_exact_and_write_control_is_clicked_once() -> None:
    request = _request()
    note = _note_for(request.payload)
    assert note == "HOME_DASHBOARD_EVENT_ID:event-1"
    assert _description_from_note(note, request.payload.ownership_marker) is None
    with_description = request.payload.model_copy(update={"description": "Human notes"})
    assert _description_from_note(_note_for(with_description), request.payload.ownership_marker) == "Human notes"
    try:
        _description_from_note("HOME_DASHBOARD_EVENT_ID:other", request.payload.ownership_marker)
    except OwnershipError:
        pass
    else:
        raise AssertionError("a different marker must fail closed")

    class Control:
        calls = 0
        def click(self):
            self.calls += 1

    control = Control()
    guard = SingleWriteAttempt()
    guard.click(control)
    assert control.calls == 1
    try:
        guard.click(control)
    except RuntimeError:
        pass
    else:
        raise AssertionError("a second remote write click must be rejected")
    assert control.calls == 1
