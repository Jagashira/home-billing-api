from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BillingRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    service_type: str
    provider_name: str
    account_id: str
    billing_month: str
    total_amount: int
    currency: str
    usage_period: str | None
    payment_status: str | None
    detail_url: str | None
    fetched_at: datetime
    source_url: str
    status: str
    raw_data_json: str | None
    raw_snapshot_path: str | None
    screenshot_path: str | None
    error_message: str | None


class BillingHistoryResponse(BaseModel):
    items: list[BillingRecordRead]
