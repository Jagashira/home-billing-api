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

    def get_time_series(
        self,
        provider_name: str,
        billing_month: str,
        account_id: str | None = None,
    ) -> list[ElectricityUsageRecord]:
        query = select(ElectricityUsageRecord).where(
            ElectricityUsageRecord.provider_name == provider_name,
            ElectricityUsageRecord.billing_month == billing_month,
        )
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)
        query = query.order_by(ElectricityUsageRecord.measured_at.asc())
        return list(self._db.scalars(query).all())

    def get_usage_summary(
        self,
        provider_name: str,
        billing_month: str,
        account_id: str | None = None,
    ) -> dict[str, object] | None:
        query = select(
            func.count(ElectricityUsageRecord.id).label("point_count"),
            func.sum(ElectricityUsageRecord.usage_kwh).label("total_usage_kwh"),
            func.avg(ElectricityUsageRecord.usage_kwh).label("average_usage_kwh"),
            func.min(ElectricityUsageRecord.usage_kwh).label("min_usage_kwh"),
            func.max(ElectricityUsageRecord.usage_kwh).label("max_usage_kwh"),
            func.min(ElectricityUsageRecord.measured_at).label("first_measured_at"),
            func.max(ElectricityUsageRecord.measured_at).label("last_measured_at"),
        ).where(
            ElectricityUsageRecord.provider_name == provider_name,
            ElectricityUsageRecord.billing_month == billing_month,
        )
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)
        row = self._db.execute(query).one()
        if row.point_count == 0:
            return None
        return {
            "provider_name": provider_name,
            "account_id": account_id,
            "billing_month": billing_month,
            "point_count": row.point_count,
            "total_usage_kwh": float(row.total_usage_kwh or 0),
            "average_usage_kwh": float(row.average_usage_kwh or 0),
            "min_usage_kwh": float(row.min_usage_kwh) if row.min_usage_kwh is not None else None,
            "max_usage_kwh": float(row.max_usage_kwh) if row.max_usage_kwh is not None else None,
            "first_measured_at": row.first_measured_at,
            "last_measured_at": row.last_measured_at,
        }
