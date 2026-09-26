from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from app.timetree.config import TimeTreeConfig

LOGGER_NAME = "app.timetree"


def configure_timetree_logging(config: TimeTreeConfig) -> logging.Logger:
    config.ensure_directories()
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    log_path = config.logs_dir / "timetree.log"
    file_handler = RotatingFileHandler(log_path, maxBytes=2_097_152, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if log_path.exists():
        log_path.chmod(0o600)
    return logger


def timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def write_private_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    path.chmod(0o600)


def capture_failure(
    *,
    config: TimeTreeConfig,
    page: Any,
    operation: str,
    error: BaseException,
) -> dict[str, str | None]:
    slug = timestamp_slug()
    destination = config.artifacts_dir / f"{slug}_{operation}"
    destination.mkdir(parents=True, exist_ok=True)
    destination.chmod(0o700)
    screenshot_path = destination / "failure.png"
    html_path = destination / "page.html" if config.debug else None

    current_url = "unknown"
    try:
        current_url = page.url
    except Exception:  # noqa: BLE001,S110 - never hide the original failure
        pass
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        screenshot_path.chmod(0o600)
    except Exception:  # noqa: BLE001 - screenshot capture is best effort
        screenshot_path = None
    if html_path is not None:
        try:
            html_path.write_text(page.content(), encoding="utf-8")
            html_path.chmod(0o600)
        except Exception:  # noqa: BLE001 - HTML capture is best effort
            html_path = None

    metadata_path = destination / "error.json"
    write_private_json(
        metadata_path,
        {
            "timestamp": datetime.now(UTC).isoformat(),
            "operation": operation,
            "url": current_url,
            "error_type": type(error).__name__,
            "error": str(error),
            "screenshot": str(screenshot_path) if screenshot_path else None,
            "html": str(html_path) if html_path else None,
        },
    )
    return {
        "metadata": str(metadata_path),
        "screenshot": str(screenshot_path) if screenshot_path else None,
        "html": str(html_path) if html_path else None,
        "url": current_url,
    }
