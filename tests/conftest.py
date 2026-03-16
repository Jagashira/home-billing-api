from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import (
    get_billing_service,
    get_electricity_usage_service,
    get_fetch_service,
    get_gas_usage_service,
)
from app.db import Base
from app.main import app
from app.services.billing_service import BillingService
from app.services.electricity_usage_service import ElectricityUsageService
from app.services.fetch_service import FetchService
from app.services.gas_usage_service import GasUsageService


SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, class_=Session)


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_billing_service() -> BillingService:
        return BillingService(db_session)

    def override_fetch_service() -> FetchService:
        return FetchService(db_session)

    def override_electricity_usage_service() -> ElectricityUsageService:
        return ElectricityUsageService(db_session)

    def override_gas_usage_service() -> GasUsageService:
        return GasUsageService(db_session)

    app.dependency_overrides[get_billing_service] = override_billing_service
    app.dependency_overrides[get_fetch_service] = override_fetch_service
    app.dependency_overrides[get_electricity_usage_service] = override_electricity_usage_service
    app.dependency_overrides[get_gas_usage_service] = override_gas_usage_service
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
