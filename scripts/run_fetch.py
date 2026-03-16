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
        (
            fetch_log,
            record,
            result,
            saved_count,
            skipped_count,
            usage_saved_count,
            usage_skipped_count,
        ) = service.run_fetch(provider_name)
        print(
            {
                "provider_name": fetch_log.provider_name,
                "success": fetch_log.success,
                "billing_record_id": record.id if record else None,
                "saved_count": saved_count,
                "skipped_count": skipped_count,
                "usage_saved_count": usage_saved_count,
                "usage_skipped_count": usage_skipped_count,
                "account_id": result.account_id if result else (record.account_id if record else None),
                "billing_month": result.billing_month if result else (record.billing_month if record else None),
                "total_amount": result.total_amount if result else (record.total_amount if record else None),
                "currency": result.currency if result else (record.currency if record else None),
                "status": result.status if result else (record.status if record else None),
                "billing_items": (
                    json.loads(result.raw_data_json).get("billing_items", [])
                    if result and result.raw_data_json
                    else None
                ),
                "usage_files": (
                    json.loads(result.raw_data_json).get("usage_files", [])
                    if result and result.raw_data_json
                    else None
                ),
                "error_code": fetch_log.error_code,
                "error_message": fetch_log.error_message,
            }
        )


if __name__ == "__main__":
    main()
