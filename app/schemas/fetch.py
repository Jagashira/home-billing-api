from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BillingSummaryItemRead(BaseModel):
    billing_month: str
    total_amount: int
    currency: str
    usage_period: str | None = None
    payment_status: str | None = None
    detail_url: str | None = None
    pdf_url: str | None = None
    csv_url: str | None = None
    csv_path: str | None = None
    usage_row_count: int | None = None


class UsageFileRead(BaseModel):
    billing_month: str
    csv_url: str
    csv_path: str | None = None
    row_count: int = 0


class FetchExecutionResponse(BaseModel):
    provider_name: str
    success: bool
    message: str
    billing_record_id: int | None = None
    saved_count: int = 0
    skipped_count: int = 0
    account_id: str | None = None
    billing_month: str | None = None
    total_amount: int | None = None
    currency: str | None = None
    status: str | None = None
    billing_items: list[BillingSummaryItemRead] | None = None
    usage_saved_count: int = 0
    usage_skipped_count: int = 0
    usage_files: list[UsageFileRead] | None = None
    error_code: str | None = None
    error_message: str | None = None
    screenshot_path: str | None = None
    html_snapshot_path: str | None = None


class FetchStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_name: str
    started_at: datetime
    finished_at: datetime | None
    success: bool
    error_code: str | None
    error_message: str | None
    screenshot_path: str | None
    html_snapshot_path: str | None
