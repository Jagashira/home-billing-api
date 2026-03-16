from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db_session
from app.services.billing_service import BillingService
from app.services.electricity_usage_service import ElectricityUsageService
from app.services.fetch_service import FetchService


def get_billing_service(db: Session = Depends(get_db_session)) -> BillingService:
    return BillingService(db)


def get_fetch_service(db: Session = Depends(get_db_session)) -> FetchService:
    return FetchService(db)


def get_electricity_usage_service(db: Session = Depends(get_db_session)) -> ElectricityUsageService:
    return ElectricityUsageService(db)
