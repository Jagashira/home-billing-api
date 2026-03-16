from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class BillingRecord(Base):
    __tablename__ = "billing_records"
    __table_args__ = (
        UniqueConstraint(
            "service_type",
            "provider_name",
            "account_id",
            "billing_month",
            name="uq_billing_records_provider_account_month",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    service_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    billing_month: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="JPY")
    usage_period: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payment_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    detail_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_snapshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    screenshot_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
