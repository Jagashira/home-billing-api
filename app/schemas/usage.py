from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ElectricityUsageRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    provider_name: str
    account_id: str
    billing_month: str
    measured_at: datetime
    usage_kwh: float
    source_url: str | None
    csv_path: str | None


class ElectricityUsageHistoryResponse(BaseModel):
    items: list[ElectricityUsageRecordRead]


class ElectricityUsageMonthSummaryRead(BaseModel):
    provider_name: str
    account_id: str
    billing_month: str
    row_count: int
    first_measured_at: datetime | None
    last_measured_at: datetime | None
    csv_path: str | None
    source_url: str | None


class ElectricityUsageMonthSummaryResponse(BaseModel):
    items: list[ElectricityUsageMonthSummaryRead]
