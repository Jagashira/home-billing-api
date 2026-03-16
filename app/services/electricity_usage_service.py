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

    def get_daily_usage(
        self,
        provider_name: str,
        billing_month: str,
        account_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = (
            select(
                func.date(ElectricityUsageRecord.measured_at).label("usage_date"),
                func.sum(ElectricityUsageRecord.usage_kwh).label("usage_kwh"),
            )
            .where(
                ElectricityUsageRecord.provider_name == provider_name,
                ElectricityUsageRecord.billing_month == billing_month,
            )
            .group_by(func.date(ElectricityUsageRecord.measured_at))
            .order_by(func.date(ElectricityUsageRecord.measured_at).asc())
        )
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)
        return [
            {
                "date": str(row.usage_date),
                "usage_kwh": float(row.usage_kwh or 0),
            }
            for row in self._db.execute(query)
        ]

    def get_hourly_usage(
        self,
        provider_name: str,
        billing_month: str,
        account_id: str | None = None,
    ) -> list[dict[str, object]]:
        query = (
            select(ElectricityUsageRecord.measured_at, ElectricityUsageRecord.usage_kwh)
            .where(
                ElectricityUsageRecord.provider_name == provider_name,
                ElectricityUsageRecord.billing_month == billing_month,
            )
            .order_by(ElectricityUsageRecord.measured_at.asc())
        )
        if account_id:
            query = query.where(ElectricityUsageRecord.account_id == account_id)

        slot_totals: dict[str, float] = {}
        slot_counts: dict[str, int] = {}
        for measured_at, usage_kwh in self._db.execute(query):
            slot = self._build_slot_label(measured_at.hour, measured_at.minute)
            slot_totals[slot] = slot_totals.get(slot, 0.0) + float(usage_kwh)
            slot_counts[slot] = slot_counts.get(slot, 0) + 1

        def sort_key(label: str) -> tuple[int, int]:
            start = label.split("-")[0]
            hour, minute = start.split(":")
            return int(hour), int(minute)

        return [
            {
                "slot": slot,
                "usage_kwh": slot_totals[slot],
                "average_usage_kwh": slot_totals[slot] / slot_counts[slot],
            }
            for slot in sorted(slot_totals.keys(), key=sort_key)
        ]

    def _build_slot_label(self, hour: int, minute: int) -> str:
        end_hour = hour
        end_minute = minute + 30
        if end_minute >= 60:
            end_hour = (hour + 1) % 24
            end_minute -= 60
        return f"{hour:02d}:{minute:02d}-{end_hour:02d}:{end_minute:02d}"
