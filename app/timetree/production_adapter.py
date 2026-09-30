from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.timetree.client import TimeTreeClient
from app.timetree.config import TimeTreeConfig
from app.schemas.timetree import TimeTreeOperationRequest, TimeTreeOperationResponse
from app.timetree.production_browser import PlaywrightProductionBackend
from app.timetree.production_models import (
    BrowserResult,
    ProductionOperationError,
    calendar_id_from_url,
    validate_request_hash,
)


class TimeTreeProductionAdapter:
    """Authenticated production boundary; it never changes Home Dashboard DB state."""

    def __init__(
        self,
        config: TimeTreeConfig | None = None,
        client_factory: Callable[[TimeTreeConfig], TimeTreeClient] = TimeTreeClient,
        backend_factory: Callable[[TimeTreeClient], PlaywrightProductionBackend] = PlaywrightProductionBackend,
    ) -> None:
        self.config = config or TimeTreeConfig.from_env()
        self.client_factory = client_factory
        self.backend_factory = backend_factory

    def status(self) -> dict[str, Any]:
        client = self.client_factory(self.config)
        auth = client.check_auth()
        authenticated = bool(auth.get("authenticated"))
        configured = bool(self.config.calendar_name)
        calendar_name: str | None = None
        calendar_url: str | None = None
        calendar_id: str | None = None
        found = False
        if authenticated and configured:
            matches = [item for item in client.list_calendars() if item.name == self.config.calendar_name]
            if len(matches) == 1:
                found = True
                calendar_name = matches[0].name
                calendar_url = matches[0].url
                calendar_id = calendar_id_from_url(calendar_url or "")
                found = calendar_id is not None
        return {
            "authenticated": authenticated,
            "storage_state_exists": bool(auth.get("storage_state_exists")),
            "calendar_configured": configured,
            "calendar_found": found,
            "calendar_name": calendar_name,
            "calendar_id": calendar_id,
            "calendar_url": calendar_url,
            "ready": authenticated and configured and found,
            "adapter_write_count": 0,
        }

    def _artifact_ref(self, before: set[str]) -> str | None:
        after = {str(path) for path in self.config.artifacts_dir.iterdir()} if self.config.artifacts_dir.exists() else set()
        created = sorted(after - before)
        return created[-1] if created else None

    def _run(self, action: str, request: TimeTreeOperationRequest) -> TimeTreeOperationResponse:
        before = {str(path) for path in self.config.artifacts_dir.iterdir()} if self.config.artifacts_dir.exists() else set()
        try:
            validate_request_hash(request)
            backend = self.backend_factory(self.client_factory(self.config))
            operation = getattr(backend, action)
            result: BrowserResult = operation(request)
            return TimeTreeOperationResponse(
                outcome="verified",
                phase="remote_verified",
                operation_id=request.operation_id,
                organizer_event_id=request.organizer_event_id,
                event_id=result.event_id,
                event_url=result.event_url,
                calendar_id=result.calendar_id,
                calendar_url=result.calendar_url,
                observed_hash=result.observed_hash,
                adapter_write_count=result.write_count,
            )
        except ValueError as exc:
            error = ProductionOperationError(
                outcome="rejected",
                phase="before_browser",
                code="invalid_request_hash",
                message=str(exc),
            )
        except ProductionOperationError as exc:
            error = exc
        except Exception as exc:
            # The adapter cannot prove whether an unexpected CREATE failure
            # happened before or after TimeTree accepted Save.  Returning an
            # uncertain result prevents the worker from blindly creating a
            # duplicate.  UPDATE/DELETE can be retried only after their stored
            # remote identity is checked again by the browser backend.
            error = ProductionOperationError(
                outcome="reconcile_required" if action == "create" else "retryable_error",
                phase="save_attempted" if action == "create" else "before_browser",
                code="unexpected_adapter_error",
                message=f"{type(exc).__name__}: adapter operation failed",
            )
        return TimeTreeOperationResponse(
            outcome=error.outcome,
            phase=error.phase,
            operation_id=request.operation_id,
            organizer_event_id=request.organizer_event_id,
            error_code=error.code,
            error_message=error.safe_message,
            artifact_ref=self._artifact_ref(before),
            adapter_write_count=error.write_count,
        )

    def create(self, request: TimeTreeOperationRequest) -> TimeTreeOperationResponse:
        return self._run("create", request)

    def reconcile(self, request: TimeTreeOperationRequest) -> TimeTreeOperationResponse:
        return self._run("reconcile", request)

    def update(self, request: TimeTreeOperationRequest) -> TimeTreeOperationResponse:
        return self._run("update", request)

    def delete(self, request: TimeTreeOperationRequest) -> TimeTreeOperationResponse:
        return self._run("delete", request)
