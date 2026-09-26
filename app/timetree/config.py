from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_BASE_URL = "https://timetreeapp.com"


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TimeTreeConfig:
    data_dir: Path
    calendar_name: str
    base_url: str = DEFAULT_BASE_URL
    headless: bool = True
    debug: bool = False
    timeout_ms: int = 30_000

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "timetreeapp.com"
            or parsed.netloc != "timetreeapp.com"
            or parsed.username
            or parsed.password
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("TIMETREE_BASE_URL must be exactly the HTTPS timetreeapp.com origin.")
        if self.timeout_ms < 1_000 or self.timeout_ms > 300_000:
            raise ValueError("TIMETREE_TIMEOUT_MS must be between 1000 and 300000.")

    @classmethod
    def from_env(
        cls,
        *,
        data_dir: str | Path | None = None,
        calendar_name: str | None = None,
        headless: bool | None = None,
        debug: bool | None = None,
    ) -> TimeTreeConfig:
        configured_dir = data_dir or os.getenv("TIMETREE_DATA_DIR", "/data/timetree")
        return cls(
            data_dir=Path(configured_dir).expanduser().resolve(),
            calendar_name=(calendar_name or os.getenv("TIMETREE_CALENDAR_NAME", "")).strip(),
            base_url=os.getenv("TIMETREE_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
            headless=_bool_env("TIMETREE_HEADLESS", True) if headless is None else headless,
            debug=_bool_env("TIMETREE_DEBUG", False) if debug is None else debug,
            timeout_ms=int(os.getenv("TIMETREE_TIMEOUT_MS", "30000")),
        )

    @property
    def sign_in_url(self) -> str:
        return f"{self.base_url}/signin"

    @property
    def auth_dir(self) -> Path:
        return self.data_dir / "auth"

    @property
    def storage_state_path(self) -> Path:
        return self.auth_dir / "storage-state.json"

    @property
    def auth_metadata_path(self) -> Path:
        return self.auth_dir / "session.json"

    @property
    def registry_path(self) -> Path:
        return self.data_dir / "owned-events.json"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def traces_dir(self) -> Path:
        return self.data_dir / "traces"

    def ensure_directories(self) -> None:
        for path in (
            self.data_dir,
            self.auth_dir,
            self.logs_dir,
            self.artifacts_dir,
            self.traces_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(0o700)
        for private_file in (
            self.storage_state_path,
            self.auth_metadata_path,
            self.registry_path,
        ):
            if private_file.exists():
                private_file.chmod(0o600)
