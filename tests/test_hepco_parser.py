from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import ProviderFetchPayload
from app.providers.hepco_electricity.parser import HepcoBillingParser


def test_parser_extracts_billing_summary_and_csv_metadata(tmp_path: Path) -> None:
    parser = HepcoBillingParser()
    csv_path = tmp_path / "billing_202602.csv"
    csv_path.write_text(
        "年月日,時刻,電力量(kWh)\n2026/02/01,00:00,0.41\n2026/02/01,00:30,0.38\n",
        encoding="utf-8",
    )
    html = """
    <html>
      <body>
        <select id="Electric_SelectedIndex">
          <option selected="selected">621-001-015806-0  江頭 慧 千葉県野田市山崎</option>
        </select>
        <table class="table table-bordered billing-info-table">
          <tr>
            <th>ご請求年月</th>
            <td class="text-center">
              <select id="Electric_SelectedHistoryIndex">
                <option selected="selected" value="202602">2026年2月分</option>
              </select>
            </td>
            <th>お支払い方法</th>
            <td class="text-center"><span class="fts-18">口振（銀行）・クレカ</span></td>
          </tr>
          <tr>
            <th>ご請求合計金額</th>
            <td colspan="3" class="text-right">
              <span class="amount">7,910</span><span class="fts-16">円（消費税込）</span>
            </td>
          </tr>
        </table>
        <a href="/hepco/mypage/usages/BillingInfoPdf/0?year=2026&amp;month=2&amp;page=Billing">PDF</a>
        <a href="/hepco/mypage/usages/BillingInfoCsvByMonth/0?year=2026&amp;month=2&amp;page=Billing">CSV</a>
      </body>
    </html>
    """
    result = parser.parse(
        ProviderFetchPayload(
            html=html,
            source_url="https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
            html_snapshot_path=None,
            screenshot_path=None,
            auxiliary_data={
                "billing_pages": [
                    {
                        "billing_month": "2026年2月分",
                        "source_url": "https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
                        "html": html,
                        "csv_url": "https://www.epower-portal.com/hepco/mypage/usages/BillingInfoCsvByMonth/0?year=2026&month=2&page=Billing",
                        "csv_path": str(csv_path),
                        "pdf_url": "https://www.epower-portal.com/hepco/mypage/usages/BillingInfoPdf/0?year=2026&month=2&page=Billing",
                    }
                ]
            },
        )
    )
    assert result.provider_name == "hepco_electricity"
    assert result.account_id == "621-001-015806-0"
    assert result.billing_month == "2026年2月分"
    assert result.total_amount == 7910
    assert len(result.billing_items or []) == 1
    assert result.billing_items[0].payment_status == "口振（銀行）・クレカ"
    assert result.billing_items[0].usage_row_count == 2
    assert result.billing_items[0].csv_path == str(csv_path)
    assert result.usage_files[0].row_count == 2
    assert len(result.usage_records or []) == 2


def test_parser_supports_wide_csv_format(tmp_path: Path) -> None:
    parser = HepcoBillingParser()
    csv_path = tmp_path / "billing_202601.csv"
    csv_path.write_text(
        "年月日,00:00,00:30\n2026/01/01,0.52,0.48\n",
        encoding="utf-8",
    )
    html = """
    <html>
      <body>
        <select id="Electric_SelectedIndex">
          <option selected="selected">621-001-015806-0  江頭 慧 千葉県野田市山崎</option>
        </select>
        <table class="table table-bordered billing-info-table">
          <tr>
            <th>ご請求年月</th>
            <td class="text-center">
              <select id="Electric_SelectedHistoryIndex">
                <option selected="selected" value="202601">2026年1月分</option>
              </select>
            </td>
            <th>お支払い方法</th>
            <td class="text-center"><span class="fts-18">口振（銀行）・クレカ</span></td>
          </tr>
          <tr>
            <th>ご請求合計金額</th>
            <td colspan="3" class="text-right"><span class="amount">6,100</span></td>
          </tr>
        </table>
      </body>
    </html>
    """
    result = parser.parse(
        ProviderFetchPayload(
            html=html,
            source_url="https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
            html_snapshot_path=None,
            screenshot_path=None,
            auxiliary_data={
                "billing_pages": [
                    {
                        "billing_month": "2026年1月分",
                        "source_url": "https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
                        "html": html,
                        "csv_url": "https://example.com/billing.csv",
                        "csv_path": str(csv_path),
                        "pdf_url": None,
                    }
                ]
            },
        )
    )
    assert len(result.usage_records or []) == 2
    assert result.usage_records[0].usage_kwh == 0.52


def test_parser_raises_clear_error_when_contract_selector_missing() -> None:
    parser = HepcoBillingParser()
    html = """
    <html>
      <body>
        <table class="table table-bordered billing-info-table">
          <tr>
            <th>ご請求年月</th>
            <td class="text-center">
              <select id="Electric_SelectedHistoryIndex">
                <option selected="selected" value="202602">2026年2月分</option>
              </select>
            </td>
          </tr>
          <tr>
            <th>ご請求合計金額</th>
            <td colspan="3" class="text-right"><span class="amount">7,910</span></td>
          </tr>
        </table>
      </body>
    </html>
    """
    with pytest.raises(ProviderError) as exc_info:
        parser.parse(
            ProviderFetchPayload(
                html=html,
                source_url="https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
                html_snapshot_path=None,
                screenshot_path=None,
            )
        )
    assert exc_info.value.code == ErrorCode.REQUIRED_FIELD_MISSING
