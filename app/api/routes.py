from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_billing_service, get_fetch_service
from app.schemas.billing import BillingHistoryResponse, BillingRecordRead
from app.schemas.fetch import BillingSummaryItemRead, FetchExecutionResponse, FetchStatusRead
from app.schemas.provider import ProviderInfo
from app.services.billing_service import BillingService
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
    fetch_log, record, saved_count, skipped_count = fetch_service.run_fetch("softbank_internet")
    billing_items = None
    if record and record.raw_data_json:
        billing_items = [
            BillingSummaryItemRead(
                billing_month=item["billing_month"],
                total_amount=item["total_amount"],
                currency=item["currency"],
                usage_period=item.get("usage_period"),
                payment_status=item.get("payment_status"),
                detail_url=item.get("detail_url"),
            )
            for item in json.loads(record.raw_data_json).get("billing_items", [])
        ]
    return FetchExecutionResponse(
        provider_name=fetch_log.provider_name,
        success=fetch_log.success,
        message="Fetch completed successfully." if fetch_log.success else "Fetch failed.",
        billing_record_id=record.id if record else None,
        saved_count=saved_count,
        skipped_count=skipped_count,
        account_id=record.account_id if record else None,
        billing_month=record.billing_month if record else None,
        total_amount=record.total_amount if record else None,
        currency=record.currency if record else None,
        status=record.status if record else None,
        billing_items=billing_items,
        error_code=fetch_log.error_code,
        error_message=fetch_log.error_message,
        screenshot_path=fetch_log.screenshot_path,
        html_snapshot_path=fetch_log.html_snapshot_path,
    )


@router.get("/api/fetch/status", response_model=FetchStatusRead | None)
def get_fetch_status(
    fetch_service: FetchService = Depends(get_fetch_service),
) -> FetchStatusRead | None:
    fetch_log = fetch_service.get_latest_fetch_status()
    if fetch_log is None:
        return None
    return FetchStatusRead.model_validate(fetch_log)
