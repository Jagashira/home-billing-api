from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GasMonthlyUsageRead(BaseModel):
    provider_name: str
    account_id: str
    billing_month: str
    usage_value: float | None
    usage_unit: str | None
    usage_days: int | None
    charge_amount: int
    currency: str
    detail_url: str | None
    source_url: str
    fetched_at: datetime


class GasMonthlyUsageResponse(BaseModel):
    items: list[GasMonthlyUsageRead]
