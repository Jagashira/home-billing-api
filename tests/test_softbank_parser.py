from __future__ import annotations

import pytest

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import ProviderFetchPayload
from app.providers.softbank_internet.parser import SoftbankBillingParser


def test_parser_supports_selector_based_amount_extraction() -> None:
    parser = SoftbankBillingParser()
    html = """
    <html>
      <body>
        <div id="account-id">test-account</div>
        <div id="billing-month">2026/03</div>
        <div id="total-amount">7,123円</div>
      </body>
    </html>
    """
    result = parser.parse(
        ProviderFetchPayload(
            html=html,
            source_url="https://example.com/billing",
            html_snapshot_path="snapshots/example.html",
            screenshot_path="snapshots/example.png",
        )
    )
    assert result.account_id == "test-account"
    assert result.billing_month == "2026/03"
    assert result.total_amount == 7123


def test_parser_supports_label_based_amount_extraction() -> None:
    parser = SoftbankBillingParser()
    html = """
    <html>
      <body>
        <div>S-ID</div><div>sid-001</div>
        <div>請求月</div><div>2026年3月</div>
        <div>ご請求金額</div><div>8,456円</div>
      </body>
    </html>
    """
    result = parser.parse(
        ProviderFetchPayload(
            html=html,
            source_url="https://example.com/billing",
            html_snapshot_path=None,
            screenshot_path=None,
        )
    )
    assert result.account_id == "sid-001"
    assert result.billing_month == "2026年3月"
    assert result.total_amount == 8456


def test_parser_raises_clear_error_when_amount_missing() -> None:
    parser = SoftbankBillingParser()
    html = """
    <html>
      <body>
        <div id="account-id">test-account</div>
        <div id="billing-month">2026/03</div>
      </body>
    </html>
    """
    with pytest.raises(ProviderError) as exc_info:
        parser.parse(
            ProviderFetchPayload(
                html=html,
                source_url="https://example.com/billing",
                html_snapshot_path=None,
                screenshot_path=None,
            )
        )
    assert exc_info.value.code == ErrorCode.PARSE_FAILED

