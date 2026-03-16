from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.api.dependencies import get_billing_service, get_electricity_usage_service, get_fetch_service
from app.schemas.billing import BillingHistoryResponse, BillingRecordRead
from app.schemas.fetch import BillingSummaryItemRead, FetchExecutionResponse, FetchStatusRead, UsageFileRead
from app.schemas.provider import ProviderInfo
from app.schemas.usage import (
    ElectricityUsageHistoryResponse,
    ElectricityUsageMonthSummaryRead,
    ElectricityUsageMonthSummaryResponse,
    ElectricityUsagePointRead,
    ElectricityUsageRecordRead,
    ElectricityUsageSummaryRead,
    ElectricityUsageTimeSeriesResponse,
)
from app.services.billing_service import BillingService
from app.services.electricity_usage_service import ElectricityUsageService
from app.services.fetch_service import FetchService


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/providers", response_model=list[ProviderInfo])
def list_providers(fetch_service: FetchService = Depends(get_fetch_service)) -> list[ProviderInfo]:
    return [ProviderInfo.model_validate(item) for item in fetch_service.list_providers()]


@router.get("/api/billing/latest", response_model=list[BillingRecordRead])
def get_latest_billing(
    billing_service: BillingService = Depends(get_billing_service),
) -> list[BillingRecordRead]:
    return [BillingRecordRead.model_validate(item) for item in billing_service.get_latest_records()]


@router.get("/api/billing/latest/internet", response_model=list[BillingRecordRead])
def get_latest_internet_billing(
    billing_service: BillingService = Depends(get_billing_service),
) -> list[BillingRecordRead]:
    return [
        BillingRecordRead.model_validate(item)
        for item in billing_service.get_latest_records(service_type="internet")
    ]


@router.get("/api/billing/latest/electricity", response_model=list[BillingRecordRead])
def get_latest_electricity_billing(
    billing_service: BillingService = Depends(get_billing_service),
) -> list[BillingRecordRead]:
    return [
        BillingRecordRead.model_validate(item)
        for item in billing_service.get_latest_records(service_type="electricity")
    ]


@router.get("/api/usage/electricity", response_model=ElectricityUsageHistoryResponse)
def get_electricity_usage(
    provider_name: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    billing_month: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    usage_service: ElectricityUsageService = Depends(get_electricity_usage_service),
) -> ElectricityUsageHistoryResponse:
    items = usage_service.get_usage_rows(
        provider_name=provider_name,
        account_id=account_id,
        billing_month=billing_month,
        limit=limit,
    )
    return ElectricityUsageHistoryResponse(items=[ElectricityUsageRecordRead.model_validate(item) for item in items])


@router.get("/api/usage/electricity/months", response_model=ElectricityUsageMonthSummaryResponse)
def get_electricity_usage_months(
    provider_name: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    limit: int = Query(default=24, ge=1, le=120),
    usage_service: ElectricityUsageService = Depends(get_electricity_usage_service),
) -> ElectricityUsageMonthSummaryResponse:
    items = usage_service.get_month_summaries(
        provider_name=provider_name,
        account_id=account_id,
        limit=limit,
    )
    return ElectricityUsageMonthSummaryResponse(
        items=[ElectricityUsageMonthSummaryRead.model_validate(item) for item in items]
    )


@router.get("/api/usage/electricity/timeseries", response_model=ElectricityUsageTimeSeriesResponse)
def get_electricity_usage_timeseries(
    billing_month: str = Query(...),
    provider_name: str = Query(default="hepco_electricity"),
    account_id: str | None = Query(default=None),
    usage_service: ElectricityUsageService = Depends(get_electricity_usage_service),
) -> ElectricityUsageTimeSeriesResponse:
    items = usage_service.get_time_series(
        provider_name=provider_name,
        billing_month=billing_month,
        account_id=account_id,
    )
    if not items:
        raise HTTPException(status_code=404, detail="Electricity usage timeseries not found.")
    return ElectricityUsageTimeSeriesResponse(
        provider_name=provider_name,
        account_id=account_id or items[0].account_id,
        billing_month=billing_month,
        points=[
            ElectricityUsagePointRead(
                measured_at=item.measured_at,
                usage_kwh=item.usage_kwh,
            )
            for item in items
        ],
    )


@router.get("/api/usage/electricity/summary", response_model=ElectricityUsageSummaryRead)
def get_electricity_usage_summary(
    billing_month: str = Query(...),
    provider_name: str = Query(default="hepco_electricity"),
    account_id: str | None = Query(default=None),
    usage_service: ElectricityUsageService = Depends(get_electricity_usage_service),
) -> ElectricityUsageSummaryRead:
    item = usage_service.get_usage_summary(
        provider_name=provider_name,
        billing_month=billing_month,
        account_id=account_id,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Electricity usage summary not found.")
    return ElectricityUsageSummaryRead.model_validate(item)


@router.get("/api/usage/electricity/csv")
def get_electricity_usage_csv(
    billing_month: str = Query(...),
    provider_name: str = Query(default="hepco_electricity"),
    account_id: str | None = Query(default=None),
    usage_service: ElectricityUsageService = Depends(get_electricity_usage_service),
) -> FileResponse:
    csv_path = usage_service.get_csv_path(
        provider_name=provider_name,
        billing_month=billing_month,
        account_id=account_id,
    )
    if not csv_path:
        raise HTTPException(status_code=404, detail="CSV not found for the specified billing month.")
    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise HTTPException(status_code=404, detail="Saved CSV file does not exist on disk.")
    return FileResponse(path=csv_file, media_type="text/csv", filename=csv_file.name)


@router.get("/api/billing/history", response_model=BillingHistoryResponse)
def get_billing_history(
    provider_name: str | None = Query(default=None),
    service_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    billing_service: BillingService = Depends(get_billing_service),
) -> BillingHistoryResponse:
    items = billing_service.get_history(
        provider_name=provider_name,
        service_type=service_type,
        limit=limit,
    )
    return BillingHistoryResponse(items=[BillingRecordRead.model_validate(item) for item in items])


@router.post("/api/fetch/softbank_internet", response_model=FetchExecutionResponse)
def run_softbank_fetch(
    fetch_service: FetchService = Depends(get_fetch_service),
) -> FetchExecutionResponse:
    fetch_log, record, result, saved_count, skipped_count, usage_saved_count, usage_skipped_count = (
        fetch_service.run_fetch("softbank_internet")
    )
    return _build_fetch_execution_response(
        fetch_log=fetch_log,
        record=record,
        result=result,
        saved_count=saved_count,
        skipped_count=skipped_count,
        usage_saved_count=usage_saved_count,
        usage_skipped_count=usage_skipped_count,
    )


@router.post("/api/fetch/hepco_electricity", response_model=FetchExecutionResponse)
def run_hepco_fetch(
    fetch_service: FetchService = Depends(get_fetch_service),
) -> FetchExecutionResponse:
    fetch_log, record, result, saved_count, skipped_count, usage_saved_count, usage_skipped_count = (
        fetch_service.run_fetch("hepco_electricity")
    )
    return _build_fetch_execution_response(
        fetch_log=fetch_log,
        record=record,
        result=result,
        saved_count=saved_count,
        skipped_count=skipped_count,
        usage_saved_count=usage_saved_count,
        usage_skipped_count=usage_skipped_count,
    )


@router.get("/api/fetch/status", response_model=FetchStatusRead | None)
def get_fetch_status(
    fetch_service: FetchService = Depends(get_fetch_service),
) -> FetchStatusRead | None:
    fetch_log = fetch_service.get_latest_fetch_status()
    if fetch_log is None:
        return None
    return FetchStatusRead.model_validate(fetch_log)


def _build_fetch_execution_response(
    *,
    fetch_log,
    record,
    result,
    saved_count: int,
    skipped_count: int,
    usage_saved_count: int,
    usage_skipped_count: int,
) -> FetchExecutionResponse:
    payload = json.loads(result.raw_data_json) if result and result.raw_data_json else {}
    billing_items = [
        BillingSummaryItemRead(
            billing_month=item["billing_month"],
            total_amount=item["total_amount"],
            currency=item["currency"],
            usage_period=item.get("usage_period"),
            payment_status=item.get("payment_status"),
            detail_url=item.get("detail_url"),
            pdf_url=item.get("pdf_url"),
            csv_url=item.get("csv_url"),
            csv_path=item.get("csv_path"),
            usage_row_count=item.get("usage_row_count"),
        )
        for item in payload.get("billing_items", [])
    ] or None
    usage_files = [
        UsageFileRead(
            billing_month=item["billing_month"],
            csv_url=item["csv_url"],
            csv_path=item.get("csv_path"),
            row_count=item.get("row_count", 0),
        )
        for item in payload.get("usage_files", [])
    ] or None
    return FetchExecutionResponse(
        provider_name=fetch_log.provider_name,
        success=fetch_log.success,
        message="Fetch completed successfully." if fetch_log.success else "Fetch failed.",
        billing_record_id=record.id if record else None,
        saved_count=saved_count,
        skipped_count=skipped_count,
        account_id=result.account_id if result else (record.account_id if record else None),
        billing_month=result.billing_month if result else (record.billing_month if record else None),
        total_amount=result.total_amount if result else (record.total_amount if record else None),
        currency=result.currency if result else (record.currency if record else None),
        status=result.status if result else (record.status if record else None),
        billing_items=billing_items,
        usage_saved_count=usage_saved_count,
        usage_skipped_count=usage_skipped_count,
        usage_files=usage_files,
        error_code=fetch_log.error_code,
        error_message=fetch_log.error_message,
        screenshot_path=fetch_log.screenshot_path,
        html_snapshot_path=fetch_log.html_snapshot_path,
    )
