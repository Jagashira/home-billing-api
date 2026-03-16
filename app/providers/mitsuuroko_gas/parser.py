from __future__ import annotations

import json
import re
from datetime import datetime

from bs4 import BeautifulSoup

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import BillingSummaryItem, Parser, ProviderFetchPayload, ProviderFetchResult
from app.providers.base.utils import normalize_amount_to_yen


class MitsuurokoGasParser(Parser):
    def parse(self, payload: ProviderFetchPayload) -> ProviderFetchResult:
        charge_html = (payload.auxiliary_data or {}).get("charge_html") or payload.html
        soup = BeautifulSoup(charge_html, "html.parser")
        billing_items = self._parse_billing_items(soup, payload.source_url)
        if not billing_items:
            raise ProviderError(
                ErrorCode.PARSE_FAILED,
                "Failed to parse Mitsuuroko gas monthly table.",
                screenshot_path=payload.screenshot_path,
                html_snapshot_path=payload.html_snapshot_path,
            )

        latest_item = billing_items[0]
        raw_summary = {
            "account_id": "default",
            "billing_month": latest_item.billing_month,
            "total_amount": latest_item.total_amount,
            "billing_items": [
                {
                    "billing_month": item.billing_month,
                    "total_amount": item.total_amount,
                    "currency": item.currency,
                    "usage_value": item.usage_value,
                    "usage_unit": item.usage_unit,
                    "usage_days": item.usage_days,
                }
                for item in billing_items
            ],
        }
        return ProviderFetchResult(
            service_type="gas",
            provider_name="mitsuuroko_gas",
            account_id="default",
            billing_month=latest_item.billing_month,
            total_amount=latest_item.total_amount,
            currency="JPY",
            fetched_at=datetime.utcnow(),
            source_url=payload.source_url,
            status="fetched",
            billing_items=billing_items,
            raw_data_json=json.dumps(raw_summary, ensure_ascii=False),
            raw_snapshot_path=payload.html_snapshot_path,
            screenshot_path=payload.screenshot_path,
        )

    def _parse_billing_items(self, soup: BeautifulSoup, source_url: str) -> list[BillingSummaryItem]:
        items: dict[str, BillingSummaryItem] = {}
        for table in soup.select(".gusTable table"):
            header_cells = table.select("thead th")
            months = [cell.get_text(strip=True) for cell in header_cells[1:]]
            rows = table.select("tbody tr")
            usage_days_row = self._find_row(rows, "ガス使用日数")
            usage_value_row = self._find_row(rows, "ガス使用量")
            charge_row = self._find_row(rows, "ガス買上額")
            if not usage_days_row or not usage_value_row or not charge_row:
                continue

            for index, month in enumerate(months, start=1):
                if not month or month == "----------":
                    continue
                usage_days = self._parse_usage_days(self._cell_text(usage_days_row, index))
                usage_value = self._parse_usage_value(self._cell_text(usage_value_row, index))
                charge_amount = self._parse_charge_amount(self._cell_text(charge_row, index))
                if usage_value is None or charge_amount is None:
                    continue
                items[month] = BillingSummaryItem(
                    billing_month=month,
                    total_amount=charge_amount,
                    currency="JPY",
                    detail_url=source_url,
                    usage_value=usage_value,
                    usage_unit="m3",
                    usage_days=usage_days,
                )

        return sorted(items.values(), key=lambda item: self._month_sort_key(item.billing_month), reverse=True)

    def _find_row(self, rows, label: str):
        for row in rows:
            header = row.select_one("th")
            if header and label in header.get_text(strip=True):
                return row
        return None

    def _cell_text(self, row, index: int) -> str:
        cells = row.select("td")
        if index - 1 >= len(cells):
            return ""
        return cells[index - 1].get_text(strip=True)

    def _parse_usage_days(self, value: str) -> int | None:
        match = re.search(r"(\d+)", value)
        return int(match.group(1)) if match else None

    def _parse_usage_value(self, value: str) -> float | None:
        normalized = value.strip().replace(",", "")
        if not normalized or normalized == "-":
            return None
        try:
            return float(normalized)
        except ValueError:
            return None

    def _parse_charge_amount(self, value: str) -> int | None:
        if not value or value == "-":
            return None
        return normalize_amount_to_yen(value)

    def _month_sort_key(self, value: str) -> int:
        match = re.search(r"(\d{4})年(\d{2})月", value)
        if not match:
            return 0
        return int(match.group(1)) * 100 + int(match.group(2))
