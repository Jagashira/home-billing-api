from __future__ import annotations


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_list_providers(client) -> None:
    response = client.get("/api/providers")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "softbank_internet"
    assert body[0]["service_type"] == "internet"


def test_empty_billing_history(client) -> None:
    response = client.get("/api/billing/history")
    assert response.status_code == 200
    assert response.json() == {"items": []}

