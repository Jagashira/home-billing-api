from __future__ import annotations

import logging
import json
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.billing_record import BillingRecord
from app.models.electricity_usage_record import ElectricityUsageRecord
from app.models.fetch_log import FetchLog
from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import BillingSummaryItem, ProviderFetchContext, ProviderFetchResult
from app.services.provider_registry import get_provider_registry


logger = logging.getLogger(__name__)


class FetchService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._registry = get_provider_registry()

    def list_providers(self) -> list[dict[str, str | bool]]:
        return [
            {
                "name": provider.metadata.name,
                "display_name": provider.metadata.display_name,
                "service_type": provider.metadata.service_type,
                "enabled": provider.is_enabled(),
                "description": provider.metadata.description,
            }
            for provider in self._registry.list()
        ]

    def run_fetch(
        self,
        provider_name: str,
    ) -> tuple[FetchLog, BillingRecord | None, ProviderFetchResult | None, int, int, int, int]:
        provider = self._registry.get(provider_name)
        started_at = datetime.utcnow()
        context = ProviderFetchContext(
            snapshots_dir=get_settings().snapshots_dir,
            run_started_at=started_at,
        )
        fetch_log = FetchLog(
            provider_name=provider_name,
            started_at=started_at,
            success=False,
        )
        self._db.add(fetch_log)
        self._db.commit()
        self._db.refresh(fetch_log)

        try:
            result = provider.fetch_billing(context)
            record, saved_count, skipped_count = self._persist_billing_records(result)
            usage_saved_count, usage_skipped_count = self._persist_usage_records(result)
            fetch_log.finished_at = datetime.utcnow()
            fetch_log.success = True
            fetch_log.screenshot_path = result.screenshot_path
            fetch_log.html_snapshot_path = result.raw_snapshot_path
            self._db.add(fetch_log)
            self._db.commit()
            self._db.refresh(fetch_log)
            logger.info("Fetch succeeded for provider=%s", provider_name)
            return (
                fetch_log,
                record,
                result,
                saved_count,
                skipped_count,
                usage_saved_count,
                usage_skipped_count,
            )
        except ProviderError as exc:
            logger.exception("Fetch failed for provider=%s", provider_name)
            fetch_log.finished_at = datetime.utcnow()
            fetch_log.success = False
            fetch_log.error_code = exc.code.value
            fetch_log.error_message = exc.message
            fetch_log.screenshot_path = exc.screenshot_path
            fetch_log.html_snapshot_path = exc.html_snapshot_path
            self._db.add(fetch_log)
            self._db.commit()
            self._db.refresh(fetch_log)
            return fetch_log, None, None, 0, 0, 0, 0
        except Exception as exc:
            logger.exception("Unexpected fetch failure for provider=%s", provider_name)
            fetch_log.finished_at = datetime.utcnow()
            fetch_log.success = False
            fetch_log.error_code = ErrorCode.UNKNOWN_ERROR.value
            fetch_log.error_message = str(exc)
            self._db.add(fetch_log)
            self._db.commit()
            self._db.refresh(fetch_log)
            return fetch_log, None, None, 0, 0, 0, 0

    def get_latest_fetch_status(self) -> FetchLog | None:
        query = select(FetchLog).order_by(desc(FetchLog.started_at)).limit(1)
        return self._db.scalar(query)

    def _persist_billing_records(self, result: ProviderFetchResult) -> tuple[BillingRecord | None, int, int]:
        try:
            billing_items = result.billing_items or [
                BillingSummaryItem(
                    billing_month=result.billing_month,
                    total_amount=result.total_amount,
                    currency=result.currency,
                )
            ]
            saved_count = 0
            skipped_count = 0
            latest_record: BillingRecord | None = None

            for index, item in enumerate(billing_items):
                existing = self._db.scalar(
                    select(BillingRecord).where(
                        BillingRecord.service_type == result.service_type,
                        BillingRecord.provider_name == result.provider_name,
                        BillingRecord.account_id == result.account_id,
                        BillingRecord.billing_month == item.billing_month,
                    )
                )
                if existing is not None:
                    skipped_count += 1
                    if index == 0:
                        latest_record = existing
                    continue

                raw_data_json = json.dumps(
                    {
                        "account_id": result.account_id,
                        "billing_month": item.billing_month,
                        "total_amount": item.total_amount,
                        "currency": item.currency,
                        "usage_period": item.usage_period,
                        "payment_status": item.payment_status,
                        "detail_url": item.detail_url,
                        "pdf_url": item.pdf_url,
                        "csv_url": item.csv_url,
                        "csv_path": item.csv_path,
                        "usage_row_count": item.usage_row_count,
                        "usage_value": item.usage_value,
                        "usage_unit": item.usage_unit,
                        "usage_days": item.usage_days,
                        "billing_items": json.loads(result.raw_data_json).get("billing_items", [])
                        if result.raw_data_json
                        else None,
                        "usage_files": json.loads(result.raw_data_json).get("usage_files", [])
                        if result.raw_data_json
                        else None,
                    },
                    ensure_ascii=False,
                )
                record = BillingRecord(
                    service_type=result.service_type,
                    provider_name=result.provider_name,
                    account_id=result.account_id,
                    billing_month=item.billing_month,
                    total_amount=item.total_amount,
                    currency=item.currency,
                    usage_period=item.usage_period,
                    payment_status=item.payment_status,
                    detail_url=item.detail_url,
                    fetched_at=result.fetched_at,
                    source_url=result.source_url,
                    status=result.status,
                    raw_data_json=raw_data_json,
                    raw_snapshot_path=result.raw_snapshot_path,
                    screenshot_path=result.screenshot_path,
                    error_message=result.error_message,
                )
                self._db.add(record)
                self._db.flush()
                if index == 0:
                    latest_record = record
                saved_count += 1

            self._db.commit()
            if latest_record is not None:
                self._db.refresh(latest_record)
            return latest_record, saved_count, skipped_count
        except Exception as exc:
            self._db.rollback()
            raise ProviderError(
                ErrorCode.DB_WRITE_FAILED,
                f"Failed to persist billing record. {exc}",
            ) from exc

    def _persist_usage_records(self, result: ProviderFetchResult) -> tuple[int, int]:
        if not result.usage_records:
            return 0, 0

        try:
            saved_count = 0
            skipped_count = 0
            for item in result.usage_records:
                existing = self._db.scalar(
                    select(ElectricityUsageRecord).where(
                        ElectricityUsageRecord.provider_name == result.provider_name,
                        ElectricityUsageRecord.account_id == result.account_id,
                        ElectricityUsageRecord.measured_at == item.measured_at,
                    )
                )
                if existing is not None:
                    skipped_count += 1
                    continue

                record = ElectricityUsageRecord(
                    provider_name=result.provider_name,
                    account_id=result.account_id,
                    billing_month=item.billing_month,
                    measured_at=item.measured_at,
                    usage_kwh=item.usage_kwh,
                    source_url=item.source_url,
                    csv_path=item.csv_path,
                )
                self._db.add(record)
                saved_count += 1
            self._db.commit()
            return saved_count, skipped_count
        except Exception as exc:
            self._db.rollback()
            raise ProviderError(
                ErrorCode.DB_WRITE_FAILED,
                f"Failed to persist electricity usage record. {exc}",
            ) from exc
