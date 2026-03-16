from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ElectricityUsageRecord(Base):
    __tablename__ = "electricity_usage_records"
    __table_args__ = (
        UniqueConstraint(
            "provider_name",
            "account_id",
            "measured_at",
            name="uq_electricity_usage_provider_account_measured_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    billing_month: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    usage_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    csv_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
