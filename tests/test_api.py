from __future__ import annotations

from datetime import datetime

from app.models.billing_record import BillingRecord
from app.models.electricity_usage_record import ElectricityUsageRecord


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_providers(client) -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [item["name"] for item in body] == ["softbank_internet", "hepco_electricity", "mitsuuroko_gas"]
    assert [item["service_type"] for item in body] == ["internet", "electricity", "gas"]


def test_empty_billing_history(client) -> None:
    response = client.get("/api/billing/history")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_empty_latest_electricity_billing(client) -> None:
    response = client.get("/api/billing/latest/electricity")
    assert response.status_code == 200
    assert response.json() == []


def test_empty_electricity_usage_history(client) -> None:
    response = client.get("/api/usage/electricity")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_empty_electricity_usage_months(client) -> None:
    response = client.get("/api/usage/electricity/months")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_empty_gas_monthly_usage(client) -> None:
    response = client.get("/api/usage/gas/monthly")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_electricity_usage_timeseries(client, db_session) -> None:
    db_session.add_all(
        [
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 0, 0),
                usage_kwh=0.41,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 30, 0),
                usage_kwh=0.38,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/usage/electricity/timeseries", params={"billing_month": "2026年2月分"})
    assert response.status_code == 200
    body = response.json()
    assert body["provider_name"] == "hepco_electricity"
    assert body["billing_month"] == "2026年2月分"
    assert body["account_id"] == "621-001-015806-0"
    assert len(body["points"]) == 2
    assert body["points"][0]["usage_kwh"] == 0.41
    assert body["points"][1]["usage_kwh"] == 0.38


def test_electricity_usage_summary(client, db_session) -> None:
    db_session.add_all(
        [
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 0, 0),
                usage_kwh=0.5,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 30, 0),
                usage_kwh=0.3,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/usage/electricity/summary", params={"billing_month": "2026年2月分"})
    assert response.status_code == 200
    body = response.json()
    assert body["billing_month"] == "2026年2月分"
    assert body["point_count"] == 2
    assert body["total_usage_kwh"] == 0.8
    assert body["average_usage_kwh"] == 0.4
    assert body["min_usage_kwh"] == 0.3
    assert body["max_usage_kwh"] == 0.5


def test_electricity_usage_daily(client, db_session) -> None:
    db_session.add_all(
        [
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 0, 0),
                usage_kwh=0.5,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 30, 0),
                usage_kwh=0.3,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 2, 0, 0, 0),
                usage_kwh=0.4,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/usage/electricity/daily", params={"billing_month": "2026年2月分"})
    assert response.status_code == 200
    body = response.json()
    assert body["days"] == [
        {"date": "2026-02-01", "usage_kwh": 0.8},
        {"date": "2026-02-02", "usage_kwh": 0.4},
    ]


def test_electricity_usage_hourly(client, db_session) -> None:
    db_session.add_all(
        [
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 0, 0),
                usage_kwh=0.5,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 2, 0, 0, 0),
                usage_kwh=0.3,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
            ElectricityUsageRecord(
                provider_name="hepco_electricity",
                account_id="621-001-015806-0",
                billing_month="2026年2月分",
                measured_at=datetime(2026, 2, 1, 0, 30, 0),
                usage_kwh=0.4,
                source_url="https://example.test/csv",
                csv_path="/tmp/test.csv",
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/usage/electricity/hourly", params={"billing_month": "2026年2月分"})
    assert response.status_code == 200
    body = response.json()
    assert body["hours"] == [
        {"slot": "00:00-00:30", "usage_kwh": 0.8, "average_usage_kwh": 0.4},
        {"slot": "00:30-01:00", "usage_kwh": 0.4, "average_usage_kwh": 0.4},
    ]


def test_gas_monthly_usage(client, db_session) -> None:
    db_session.add_all(
        [
            BillingRecord(
                service_type="gas",
                provider_name="mitsuuroko_gas",
                account_id="default",
                billing_month="2026年01月",
                total_amount=6274,
                currency="JPY",
                usage_period=None,
                payment_status=None,
                detail_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
                fetched_at=datetime(2026, 3, 17, 0, 0, 0),
                source_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
                status="fetched",
                raw_data_json='{"usage_value": 4.8, "usage_unit": "m3", "usage_days": 31}',
                raw_snapshot_path=None,
                screenshot_path=None,
                error_message=None,
            ),
            BillingRecord(
                service_type="gas",
                provider_name="mitsuuroko_gas",
                account_id="default",
                billing_month="2026年02月",
                total_amount=7158,
                currency="JPY",
                usage_period=None,
                payment_status=None,
                detail_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
                fetched_at=datetime(2026, 3, 17, 0, 0, 0),
                source_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
                status="fetched",
                raw_data_json='{"usage_value": 5.9, "usage_unit": "m3", "usage_days": 31}',
                raw_snapshot_path=None,
                screenshot_path=None,
                error_message=None,
            ),
        ]
    )
    db_session.commit()

    response = client.get("/api/usage/gas/monthly")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [
        {
            "provider_name": "mitsuuroko_gas",
            "account_id": "default",
            "billing_month": "2026年01月",
            "usage_value": 4.8,
            "usage_unit": "m3",
            "usage_days": 31,
            "charge_amount": 6274,
            "currency": "JPY",
            "detail_url": "https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
            "source_url": "https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
            "fetched_at": "2026-03-17T00:00:00",
        },
        {
            "provider_name": "mitsuuroko_gas",
            "account_id": "default",
            "billing_month": "2026年02月",
            "usage_value": 5.9,
            "usage_unit": "m3",
            "usage_days": 31,
            "charge_amount": 7158,
            "currency": "JPY",
            "detail_url": "https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
            "source_url": "https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
            "fetched_at": "2026-03-17T00:00:00",
        },
    ]
