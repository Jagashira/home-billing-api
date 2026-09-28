from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.timetree.client import TimeTreeClient
from app.timetree.config import TimeTreeConfig
from app.timetree.ownership import OwnershipRegistry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.timetree",
        description="Safe TimeTree Web Playwright proof of concept.",
    )
    parser.add_argument("--data-dir", help="Persistent private data directory (default: TIMETREE_DATA_DIR)")
    parser.add_argument("--calendar", help="Exact shared calendar name (default: TIMETREE_CALENDAR_NAME)")
    parser.add_argument("--headed", action="store_true", help="Show Chromium instead of using headless mode")
    parser.add_argument("--debug", action="store_true", help="Save HTML snapshots and Playwright traces")

    commands = parser.add_subparsers(dest="command", required=True)
    login = commands.add_parser("login", help="Perform one human-driven login on a GUI computer")
    login.add_argument("--wait-seconds", type=int, default=600)
    commands.add_parser("status", help="Check Chromium, navigation, and authentication state")
    commands.add_parser("calendars", help="List calendar links visible to the signed-in account")
    probe = commands.add_parser("probe", help="Save a screenshot and interactive-element inventory")
    probe.add_argument(
        "--surface",
        choices=("home", "create", "create-filled", "owned"),
        default="home",
    )
    probe.add_argument("--record-id", help="Owned record to open when --surface=owned")
    probe.add_argument("--date", help="YYYY-MM-DD for --surface=create-filled")
    commands.add_parser("records", help="List locally owned PoC event records")

    create = commands.add_parser("create-test", help="Create one uniquely marked PoC event")
    create.add_argument("--date", help="YYYY-MM-DD (default: tomorrow in Asia/Tokyo)")
    create.add_argument("--title", help="Human-readable title portion; PoC prefix/token are enforced")
    create.add_argument("--apply", action="store_true", help="Actually save the event; default is dry-run")

    update = commands.add_parser("update-test", help="Update one locally owned PoC event")
    update.add_argument("--record-id")
    update.add_argument("--title", help="New title portion; PoC prefix/token are enforced")
    update.add_argument("--apply", action="store_true", help="Actually save the update; default is dry-run")

    delete = commands.add_parser("delete-test", help="Delete one locally owned PoC event")
    delete.add_argument("--record-id")
    delete.add_argument("--apply", action="store_true", help="Actually confirm deletion; default is dry-run")

    cleanup = commands.add_parser("cleanup-test", help="Delete only active events in the local ownership ledger")
    cleanup.add_argument("--limit", type=int, default=10)
    cleanup.add_argument("--apply", action="store_true", help="Actually confirm deletions; default is dry-run")
    pending_cleanup = commands.add_parser(
        "pending-cleanup",
        help="Remove one exact local pending-create ledger record without opening TimeTree",
    )
    pending_cleanup.add_argument("--ownership-token", required=True)
    pending_cleanup.add_argument(
        "--apply",
        action="store_true",
        help="Actually update only the local pending ledger; default is dry-run",
    )
    return parser


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _print(value: Any) -> None:
    print(json.dumps(_json_value(value), ensure_ascii=False, indent=2, default=str))


def _parse_create_date(value: str | None) -> date:
    if value:
        # An explicit calendar date is date-only data. Do not convert it to a
        # datetime, UTC, or another timezone.
        return date.fromisoformat(value)
    return (datetime.now(ZoneInfo("Asia/Tokyo")) + timedelta(days=1)).date()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    headless = False if args.command == "login" or args.headed else None
    config = TimeTreeConfig.from_env(
        data_dir=args.data_dir,
        calendar_name=args.calendar,
        headless=headless,
        debug=args.debug or None,
    )
    try:
        if args.command == "pending-cleanup":
            registry = OwnershipRegistry(config.registry_path)
            _print(
                registry.cleanup_pending_create(
                    args.ownership_token,
                    dry_run=not args.apply,
                )
            )
            return 0
        client = TimeTreeClient(config)
        if args.command == "login":
            _print({"storage_state": client.login(wait_seconds=args.wait_seconds)})
        elif args.command == "status":
            result = client.check_auth()
            _print(result)
            return 0 if result["authenticated"] else 2
        elif args.command == "calendars":
            _print(client.list_calendars())
        elif args.command == "probe":
            probe_date = date.fromisoformat(args.date) if args.date else None
            _print(
                client.probe(
                    surface=args.surface,
                    record_id=args.record_id,
                    event_date=probe_date,
                )
            )
        elif args.command == "records":
            _print(
                {
                    "owned_events": client.registry.list(),
                    "pending_creates": client.registry.list_pending_creates(),
                }
            )
        elif args.command == "create-test":
            event_date = _parse_create_date(args.date)
            _print(client.create_event(event_date=event_date, title=args.title, dry_run=not args.apply))
        elif args.command == "update-test":
            _print(
                client.update_event(
                    record_id=args.record_id,
                    title=args.title,
                    dry_run=not args.apply,
                )
            )
        elif args.command == "delete-test":
            _print(client.delete_event(record_id=args.record_id, dry_run=not args.apply))
        elif args.command == "cleanup-test":
            _print(client.cleanup_events(dry_run=not args.apply, limit=args.limit))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary emits a structured failure
        _print({"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
