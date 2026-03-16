from __future__ import annotations


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_providers(client) -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [item["name"] for item in body] == ["softbank_internet", "hepco_electricity"]
    assert [item["service_type"] for item in body] == ["internet", "electricity"]


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
