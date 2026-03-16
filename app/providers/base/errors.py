from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    LOGIN_FAILED = "LOGIN_FAILED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    TARGET_PAGE_UNREACHABLE = "TARGET_PAGE_UNREACHABLE"
    PARSE_FAILED = "PARSE_FAILED"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    DB_WRITE_FAILED = "DB_WRITE_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ProviderError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        screenshot_path: str | None = None,
        html_snapshot_path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.screenshot_path = screenshot_path
        self.html_snapshot_path = html_snapshot_path
