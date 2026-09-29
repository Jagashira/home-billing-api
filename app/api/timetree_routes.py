from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.schemas.timetree import TimeTreeAdapterStatusRead
from app.timetree.production_adapter import TimeTreeProductionAdapter


router = APIRouter(prefix="/internal/timetree/v1", tags=["internal-timetree"])


def require_internal_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = os.getenv("TIMETREE_INTERNAL_API_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="TimeTree internal API is not configured.")
    scheme, separator, supplied = (authorization or "").partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API credentials.")


def get_timetree_production_adapter() -> TimeTreeProductionAdapter:
    return TimeTreeProductionAdapter()


@router.get(
    "/status",
    response_model=TimeTreeAdapterStatusRead,
    dependencies=[Depends(require_internal_token)],
)
def timetree_status(
    adapter: TimeTreeProductionAdapter = Depends(get_timetree_production_adapter),
) -> TimeTreeAdapterStatusRead:
    return TimeTreeAdapterStatusRead.model_validate(adapter.status())
