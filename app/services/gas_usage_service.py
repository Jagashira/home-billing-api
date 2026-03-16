from __future__ import annotations

import json

from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from app.models.billing_record import BillingRecord


class GasUsageService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_monthly_usage(
        self,
        provider_name: str = "mitsuuroko_gas",
        account_id: str | None = None,
        limit: int = 24,
    ) -> list[dict[str, object]]:
        query: Select[tuple[BillingRecord]] = (
            select(BillingRecord)
            .where(
                BillingRecord.service_type == "gas",
                BillingRecord.provider_name == provider_name,
            )
            .order_by(desc(BillingRecord.billing_month))
            .limit(limit)
        )
        if account_id:
            query = query.where(BillingRecord.account_id == account_id)

        items: list[dict[str, object]] = []
        for record in self._db.scalars(query).all():
            payload = json.loads(record.raw_data_json) if record.raw_data_json else {}
            items.append(
                {
                    "provider_name": record.provider_name,
                    "account_id": record.account_id,
                    "billing_month": record.billing_month,
                    "usage_value": payload.get("usage_value"),
                    "usage_unit": payload.get("usage_unit"),
                    "usage_days": payload.get("usage_days"),
                    "charge_amount": record.total_amount,
                    "currency": record.currency,
                    "detail_url": record.detail_url,
                    "source_url": record.source_url,
                    "fetched_at": record.fetched_at,
                }
            )
        return list(reversed(items))
