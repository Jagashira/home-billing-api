from __future__ import annotations

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from app.models.electricity_usage_record import ElectricityUsageRecord


class ElectricityUsageService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_usage_rows(
        self,
        provider_name: str | None = None,
        account_id: str | None = None,
        billing_month: str | None = None,
        limit: int = 500,
    ) -> list[ElectricityUsageRecord]:
        query: Select[tuple[ElectricityUsageRecord]] = (
            select(ElectricityUsageRecord)
            .order_by(desc(ElectricityUsageRecord.measured_at))
            .limit(limit)
        )
        if provider_name:
            query = query.where(ElectricityUsageRecord.provider_name == provider_name)
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)
        if billing_month:
            query = query.where(ElectricityUsageRecord.billing_month == billing_month)
        return list(self._db.scalars(query).all())

    def get_month_summaries(
        self,
        provider_name: str | None = None,
        account_id: str | None = None,
        limit: int = 24,
    ) -> list[dict[str, object]]:
        query = (
            select(
                ElectricityUsageRecord.provider_name,
                ElectricityUsageRecord.account_id,
                ElectricityUsageRecord.billing_month,
                func.count(ElectricityUsageRecord.id).label("row_count"),
                func.min(ElectricityUsageRecord.measured_at).label("first_measured_at"),
                func.max(ElectricityUsageRecord.measured_at).label("last_measured_at"),
                func.max(ElectricityUsageRecord.csv_path).label("csv_path"),
                func.max(ElectricityUsageRecord.source_url).label("source_url"),
            )
            .group_by(
                ElectricityUsageRecord.provider_name,
                ElectricityUsageRecord.account_id,
                ElectricityUsageRecord.billing_month,
            )
            .order_by(desc(ElectricityUsageRecord.billing_month))
            .limit(limit)
        )
        if provider_name:
            query = query.where(ElectricityUsageRecord.provider_name == provider_name)
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)

        return [
            {
                "provider_name": row.provider_name,
                "account_id": row.account_id,
                "billing_month": row.billing_month,
                "row_count": row.row_count,
                "first_measured_at": row.first_measured_at,
                "last_measured_at": row.last_measured_at,
                "csv_path": row.csv_path,
                "source_url": row.source_url,
            }
            for row in self._db.execute(query)
        ]

    def get_csv_path(
        self,
        provider_name: str,
        billing_month: str,
        account_id: str | None = None,
    ) -> str | None:
        query = select(ElectricityUsageRecord.csv_path).where(
            ElectricityUsageRecord.provider_name == provider_name,
            ElectricityUsageRecord.billing_month == billing_month,
            ElectricityUsageRecord.csv_path.is_not(None),
        )
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)
        query = query.order_by(desc(ElectricityUsageRecord.measured_at)).limit(1)
        return self._db.scalar(query)
