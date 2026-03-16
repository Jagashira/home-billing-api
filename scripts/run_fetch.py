from __future__ import annotations

import json
import sys

from app.db import SessionLocal, init_db
from app.logging import configure_logging
from app.services.fetch_service import FetchService


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python scripts/run_fetch.py <provider_name>")

    provider_name = sys.argv[1]
    configure_logging()
    init_db()
    with SessionLocal() as session:
        service = FetchService(session)
        fetch_log, record, saved_count, skipped_count = service.run_fetch(provider_name)
        print(
            {
                "provider_name": fetch_log.provider_name,
                "success": fetch_log.success,
                "billing_record_id": record.id if record else None,
                "saved_count": saved_count,
                "skipped_count": skipped_count,
                "account_id": record.account_id if record else None,
                "billing_month": record.billing_month if record else None,
                "total_amount": record.total_amount if record else None,
                "currency": record.currency if record else None,
                "status": record.status if record else None,
                "billing_items": (
                    json.loads(record.raw_data_json).get("billing_items", [])
                    if record and record.raw_data_json
                    else None
                ),
                "error_code": fetch_log.error_code,
                "error_message": fetch_log.error_message,
            }
        )


if __name__ == "__main__":
    main()
