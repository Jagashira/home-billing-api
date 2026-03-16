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


class ElectricityUsagePointRead(BaseModel):
    measured_at: datetime
    usage_kwh: float


class ElectricityUsageTimeSeriesResponse(BaseModel):
    provider_name: str
    account_id: str | None
    billing_month: str
    points: list[ElectricityUsagePointRead]


class ElectricityUsageSummaryRead(BaseModel):
    provider_name: str
    account_id: str | None
    billing_month: str
    point_count: int
    total_usage_kwh: float
    average_usage_kwh: float
    min_usage_kwh: float | None
    max_usage_kwh: float | None
    first_measured_at: datetime | None
    last_measured_at: datetime | None


class ElectricityUsageDailyPointRead(BaseModel):
    date: str
    usage_kwh: float


class ElectricityUsageDailyResponse(BaseModel):
    provider_name: str
    account_id: str | None
    billing_month: str
    days: list[ElectricityUsageDailyPointRead]


class ElectricityUsageHourlyPointRead(BaseModel):
    slot: str
    usage_kwh: float
    average_usage_kwh: float


class ElectricityUsageHourlyResponse(BaseModel):
    provider_name: str
    account_id: str | None
    billing_month: str
    hours: list[ElectricityUsageHourlyPointRead]
