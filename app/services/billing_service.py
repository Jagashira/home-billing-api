from __future__ import annotations

from sqlalchemy import Select, desc, func, select
from sqlalchemy.orm import Session

from app.models.billing_record import BillingRecord


class BillingService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_latest_records(self, service_type: str | None = None) -> list[BillingRecord]:
        subquery = (
            select(
                BillingRecord.provider_name,
                func.max(BillingRecord.fetched_at).label("max_fetched_at"),
            )
            .group_by(BillingRecord.provider_name)
            .subquery()
        )

        query = (
            select(BillingRecord)
            .join(
                subquery,
                (BillingRecord.provider_name == subquery.c.provider_name)
                & (BillingRecord.fetched_at == subquery.c.max_fetched_at),
            )
            .order_by(desc(BillingRecord.fetched_at))
        )
        if service_type:
            query = query.where(BillingRecord.service_type == service_type)
        return list(self._db.scalars(query).all())

    def get_history(
        self,
        provider_name: str | None = None,
        service_type: str | None = None,
        limit: int = 50,
    ) -> list[BillingRecord]:
        query: Select[tuple[BillingRecord]] = select(BillingRecord).order_by(desc(BillingRecord.fetched_at)).limit(limit)
        if provider_name:
            query = query.where(BillingRecord.provider_name == provider_name)
        if service_type:
            query = query.where(BillingRecord.service_type == service_type)
        return list(self._db.scalars(query).all())

