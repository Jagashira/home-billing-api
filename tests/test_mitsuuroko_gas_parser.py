from __future__ import annotations

import pytest

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import ProviderFetchPayload
from app.providers.mitsuuroko_gas.parser import MitsuurokoGasParser


def test_parser_extracts_monthly_usage_and_charge() -> None:
    parser = MitsuurokoGasParser()
    html = """
    <html>
      <body>
        <div class="gusTable">
          <table>
            <thead>
              <tr>
                <th>請求年月</th>
                <th>2025年12月</th>
                <th>2026年01月</th>
                <th>2026年02月</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <th>ガス使用日数</th>
                <td>30日</td>
                <td>31日</td>
                <td>31日</td>
              </tr>
              <tr>
                <th>ガス使用量（m&#179;）</th>
                <td>4.7</td>
                <td>4.8</td>
                <td>5.9</td>
              </tr>
              <tr>
                <th>ガス買上額（円）</th>
                <td>&yen;6,194</td>
                <td>&yen;6,274</td>
                <td>&yen;7,158</td>
              </tr>
            </tbody>
          </table>
        </div>
      </body>
    </html>
    """
    result = parser.parse(
        ProviderFetchPayload(
            html=html,
            source_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
            html_snapshot_path=None,
            screenshot_path=None,
        )
    )
    assert result.provider_name == "mitsuuroko_gas"
    assert result.account_id == "default"
    assert result.billing_month == "2026年02月"
    assert result.total_amount == 7158
    assert len(result.billing_items or []) == 3
    assert result.billing_items[0].usage_value == 5.9
    assert result.billing_items[0].usage_unit == "m3"
    assert result.billing_items[0].usage_days == 31


def test_parser_raises_when_table_missing() -> None:
    parser = MitsuurokoGasParser()
    with pytest.raises(ProviderError) as exc_info:
        parser.parse(
            ProviderFetchPayload(
                html="<html><body><div>empty</div></body></html>",
                source_url="https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
                html_snapshot_path=None,
                screenshot_path=None,
            )
        )
    assert exc_info.value.code == ErrorCode.PARSE_FAILED
