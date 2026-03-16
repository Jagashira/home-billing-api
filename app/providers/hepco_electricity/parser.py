from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import (
    BillingSummaryItem,
    ElectricityUsageRecordItem,
    Parser,
    ProviderFetchPayload,
    ProviderFetchResult,
    UsageFileItem,
)
from app.providers.base.utils import normalize_amount_to_yen


logger = logging.getLogger(__name__)


class HepcoBillingParser(Parser):
    def parse(self, payload: ProviderFetchPayload) -> ProviderFetchResult:
        try:
            billing_pages = list((payload.auxiliary_data or {}).get("billing_pages", []))
            if not billing_pages:
                billing_pages = [
                    {
                        "billing_month": None,
                        "source_url": payload.source_url,
                        "html_snapshot_path": payload.html_snapshot_path,
                        "csv_url": None,
                        "csv_path": None,
                        "pdf_url": None,
                        "html": payload.html,
                    }
                ]

            account_id = self._parse_account_id(BeautifulSoup(payload.html, "html.parser"))
            billing_items: list[BillingSummaryItem] = []
            usage_files: list[UsageFileItem] = []
            usage_records: list[ElectricityUsageRecordItem] = []

            for page_data in billing_pages:
                page_html = page_data.get("html")
                if page_html is None and page_data.get("html_snapshot_path"):
                    page_html = Path(str(page_data["html_snapshot_path"])).read_text(encoding="utf-8")
                if page_html is None:
                    continue

                soup = BeautifulSoup(page_html, "html.parser")
                item = self._parse_billing_item(
                    soup=soup,
                    source_url=str(page_data.get("source_url") or payload.source_url),
                    billing_month_hint=page_data.get("billing_month"),
                    csv_url=page_data.get("csv_url"),
                    csv_path=page_data.get("csv_path"),
                    pdf_url=page_data.get("pdf_url"),
                )
                page_usage_records = self._parse_usage_records(
                    billing_month=item.billing_month,
                    csv_path=item.csv_path,
                    source_url=item.csv_url,
                )
                billing_items.append(
                    BillingSummaryItem(
                        billing_month=item.billing_month,
                        total_amount=item.total_amount,
                        currency=item.currency,
                        usage_period=item.usage_period,
                        payment_status=item.payment_status,
                        detail_url=item.detail_url,
                        pdf_url=item.pdf_url,
                        csv_url=item.csv_url,
                        csv_path=item.csv_path,
                        usage_row_count=len(page_usage_records),
                    )
                )
                if item.csv_url:
                    usage_files.append(
                        UsageFileItem(
                            billing_month=item.billing_month,
                            csv_url=item.csv_url,
                            csv_path=item.csv_path,
                            row_count=len(page_usage_records),
                        )
                    )
                usage_records.extend(page_usage_records)

            if not billing_items:
                raise ProviderError(
                    ErrorCode.PARSE_FAILED,
                    "Failed to locate HEPCO billing summary. Update parser selectors for the current page.",
                )

            latest_item = billing_items[0]
        except ProviderError as exc:
            raise ProviderError(
                exc.code,
                exc.message,
                screenshot_path=payload.screenshot_path,
                html_snapshot_path=payload.html_snapshot_path,
            ) from exc

        raw_summary = {
            "account_id": account_id,
            "billing_month": latest_item.billing_month,
            "total_amount": latest_item.total_amount,
            "billing_items": [
                {
                    "billing_month": item.billing_month,
                    "total_amount": item.total_amount,
                    "currency": item.currency,
                    "usage_period": item.usage_period,
                    "payment_status": item.payment_status,
                    "detail_url": item.detail_url,
                    "pdf_url": item.pdf_url,
                    "csv_url": item.csv_url,
                    "csv_path": item.csv_path,
                    "usage_row_count": item.usage_row_count,
                }
                for item in billing_items
            ],
            "usage_files": [
                {
                    "billing_month": item.billing_month,
                    "csv_url": item.csv_url,
                    "csv_path": item.csv_path,
                    "row_count": item.row_count,
                }
                for item in usage_files
            ],
        }
        logger.info("HEPCO billing page parsed successfully.")
        return ProviderFetchResult(
            service_type="electricity",
            provider_name="hepco_electricity",
            account_id=account_id,
            billing_month=latest_item.billing_month,
            total_amount=latest_item.total_amount,
            currency="JPY",
            fetched_at=datetime.utcnow(),
            source_url=payload.source_url,
            status="fetched",
            billing_items=billing_items,
            usage_records=usage_records,
            usage_files=usage_files,
            raw_data_json=json.dumps(raw_summary, ensure_ascii=False),
            raw_snapshot_path=payload.html_snapshot_path,
            screenshot_path=payload.screenshot_path,
        )

    def _parse_billing_item(
        self,
        soup: BeautifulSoup,
        source_url: str,
        billing_month_hint: str | None,
        csv_url: str | None,
        csv_path: str | None,
        pdf_url: str | None,
    ) -> BillingSummaryItem:
        billing_month = billing_month_hint or self._parse_selected_history_month(soup)
        if billing_month is None:
            raise ProviderError(
                ErrorCode.REQUIRED_FIELD_MISSING,
                "HEPCO billing month is missing from the fetched page.",
            )

        amount_node = soup.select_one(".billing-info-table span.amount")
        if amount_node is None:
            raise ProviderError(
                ErrorCode.PARSE_FAILED,
                "HEPCO total amount is missing from the fetched page.",
            )

        payment_method = self._extract_cell_from_table_row(soup, "お支払い方法")
        pdf_link = pdf_url or self._extract_anchor_url(soup, source_url, "a[href*='BillingInfoPdf']")
        csv_link = csv_url or self._extract_anchor_url(soup, source_url, "a[href*='BillingInfoCsvByMonth']")

        return BillingSummaryItem(
            billing_month=billing_month,
            total_amount=normalize_amount_to_yen(amount_node.get_text(strip=True)),
            currency="JPY",
            payment_status=payment_method,
            detail_url=pdf_link,
            pdf_url=pdf_link,
            csv_url=csv_link,
            csv_path=csv_path,
        )

    def _parse_account_id(self, soup: BeautifulSoup) -> str:
        selected = soup.select_one("#Electric_SelectedIndex option[selected], #Electric_SelectedIndex option")
        if selected is None:
            raise ProviderError(
                ErrorCode.REQUIRED_FIELD_MISSING,
                "HEPCO contract selector was not found on the billing page.",
            )
        text = selected.get_text(" ", strip=True)
        match = re.search(r"(\d{3}-\d{3}-\d{6}-\d)", text)
        if match:
            return match.group(1)
        account_id = text.split()[0].strip()
        if account_id:
            return account_id
        raise ProviderError(
            ErrorCode.REQUIRED_FIELD_MISSING,
            "HEPCO account ID could not be parsed from the selected contract text.",
        )

    def _parse_selected_history_month(self, soup: BeautifulSoup) -> str | None:
        selected = soup.select_one("#Electric_SelectedHistoryIndex option[selected]")
        if selected is None:
            selected = soup.select_one("#Electric_SelectedHistoryIndex option")
        if selected is None:
            return None
        return selected.get_text(strip=True)

    def _extract_cell_from_table_row(self, soup: BeautifulSoup, label: str) -> str | None:
        for row in soup.select(".billing-info-table tr"):
            header = row.select_one("th")
            if header is None or header.get_text(strip=True) != label:
                continue
            cells = row.select("td")
            if not cells:
                return None
            return cells[-1].get_text(" ", strip=True) or None
        return None

    def _extract_anchor_url(self, soup: BeautifulSoup, source_url: str, selector: str) -> str | None:
        node = soup.select_one(selector)
        if node is None or not node.get("href"):
            return None
        return urljoin(source_url, str(node.get("href")))

    def _parse_usage_records(
        self,
        billing_month: str,
        csv_path: str | None,
        source_url: str | None,
    ) -> list[ElectricityUsageRecordItem]:
        if not csv_path:
            return []
        csv_file = Path(csv_path)
        if not csv_file.exists():
            return []

        text = self._decode_csv(csv_file.read_bytes())
        rows = list(csv.reader(io.StringIO(text)))
        if not rows:
            return []

        tall_format_records = self._parse_tall_csv(rows, billing_month, csv_path, source_url)
        if tall_format_records:
            return tall_format_records
        matrix_format_records = self._parse_matrix_csv(rows, billing_month, csv_path, source_url)
        if matrix_format_records:
            return matrix_format_records
        return self._parse_wide_csv(rows, billing_month, csv_path, source_url)

    def _decode_csv(self, payload: bytes) -> str:
        for encoding in ("utf-8-sig", "cp932", "shift_jis", "utf-8"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ProviderError(
            ErrorCode.PARSE_FAILED,
            "Failed to decode HEPCO CSV. Supported encodings utf-8-sig/cp932/shift_jis were not matched.",
        )

    def _parse_tall_csv(
        self,
        rows: list[list[str]],
        billing_month: str,
        csv_path: str,
        source_url: str | None,
    ) -> list[ElectricityUsageRecordItem]:
        header = rows[0]
        normalized_header = [cell.strip() for cell in header]
        date_index = self._find_header_index(normalized_header, ("年月日", "日付", "Date", "DATE"))
        time_index = self._find_header_index(normalized_header, ("時刻", "時間", "Time", "TIME", "開始時刻"))
        usage_index = self._find_header_index(
            normalized_header,
            ("電力量(kWh)", "電力量（kWh）", "使用量(kWh)", "使用電力量(kWh)", "ご使用量(kWh)", "kWh"),
        )
        if date_index is None or time_index is None or usage_index is None:
            return []

        records: list[ElectricityUsageRecordItem] = []
        for row in rows[1:]:
            if max(date_index, time_index, usage_index) >= len(row):
                continue
            measured_at = self._parse_datetime(row[date_index], row[time_index])
            usage_kwh = self._parse_usage_value(row[usage_index])
            if measured_at is None or usage_kwh is None:
                continue
            records.append(
                ElectricityUsageRecordItem(
                    billing_month=billing_month,
                    measured_at=measured_at,
                    usage_kwh=usage_kwh,
                    csv_path=csv_path,
                    source_url=source_url,
                )
            )
        return records

    def _parse_wide_csv(
        self,
        rows: list[list[str]],
        billing_month: str,
        csv_path: str,
        source_url: str | None,
    ) -> list[ElectricityUsageRecordItem]:
        header = [cell.strip() for cell in rows[0]]
        date_index = self._find_header_index(header, ("年月日", "日付", "Date", "DATE"))
        if date_index is None:
            return []

        time_columns = [
            (index, value)
            for index, value in enumerate(header)
            if self._looks_like_time_label(value)
        ]
        if not time_columns:
            return []

        records: list[ElectricityUsageRecordItem] = []
        for row in rows[1:]:
            if date_index >= len(row):
                continue
            date_value = row[date_index]
            for index, time_label in time_columns:
                if index >= len(row):
                    continue
                measured_at = self._parse_datetime(date_value, time_label)
                usage_kwh = self._parse_usage_value(row[index])
                if measured_at is None or usage_kwh is None:
                    continue
                records.append(
                    ElectricityUsageRecordItem(
                        billing_month=billing_month,
                        measured_at=measured_at,
                        usage_kwh=usage_kwh,
                        csv_path=csv_path,
                        source_url=source_url,
                    )
                )
        return records

    def _parse_matrix_csv(
        self,
        rows: list[list[str]],
        billing_month: str,
        csv_path: str,
        source_url: str | None,
    ) -> list[ElectricityUsageRecordItem]:
        if len(rows) < 9:
            return []

        year_row = rows[4]
        month_row = rows[5]
        day_row = rows[6]

        if not year_row or not month_row or not day_row:
            return []
        if not year_row[0].strip().startswith("年"):
            return []
        if not month_row[0].strip().startswith("月"):
            return []
        if not day_row[0].strip().startswith("日"):
            return []

        date_columns: list[tuple[int, str]] = []
        current_year: int | None = None
        current_month: int | None = None
        last_data_column = max(1, len(day_row) - 2)

        for index in range(1, last_data_column):
            year_value = year_row[index].strip() if index < len(year_row) else ""
            month_value = month_row[index].strip() if index < len(month_row) else ""
            day_value = day_row[index].strip() if index < len(day_row) else ""

            if year_value:
                year_match = re.search(r"(\d{4})", year_value)
                if year_match:
                    current_year = int(year_match.group(1))
            if month_value:
                month_match = re.search(r"(\d{1,2})", month_value)
                if month_match:
                    current_month = int(month_match.group(1))
            if current_year is None or current_month is None:
                continue
            if not day_value.isdigit():
                continue

            date_columns.append((index, f"{current_year:04d}/{current_month:02d}/{int(day_value):02d}"))

        if not date_columns:
            return []

        records: list[ElectricityUsageRecordItem] = []
        for row in rows[8:]:
            if not row:
                continue
            slot = row[0].strip()
            if not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}", slot):
                continue

            start_time, _, _ = slot.partition("-")
            for column_index, date_value in date_columns:
                if column_index >= len(row):
                    continue
                measured_at = self._parse_datetime(date_value, start_time)
                usage_kwh = self._parse_usage_value(row[column_index])
                if measured_at is None or usage_kwh is None:
                    continue
                records.append(
                    ElectricityUsageRecordItem(
                        billing_month=billing_month,
                        measured_at=measured_at,
                        usage_kwh=usage_kwh,
                        csv_path=csv_path,
                        source_url=source_url,
                    )
                )
        return records

    def _find_header_index(self, header: list[str], candidates: tuple[str, ...]) -> int | None:
        for index, value in enumerate(header):
            if value in candidates:
                return index
        return None

    def _looks_like_time_label(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{1,2}:\d{2}", value.strip())) or bool(
            re.fullmatch(r"\d{1,2}時\d{2}分", value.strip())
        )

    def _parse_datetime(self, date_value: str, time_value: str) -> datetime | None:
        date_value = date_value.strip()
        time_value = time_value.strip()
        if not date_value or not time_value:
            return None

        base_date = None
        for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日"):
            try:
                base_date = datetime.strptime(date_value, fmt)
                break
            except ValueError:
                continue
        if base_date is None:
            return None

        time_match = re.fullmatch(r"(\d{1,2})[:時](\d{2})(?:分)?", time_value)
        if not time_match:
            return None

        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if hour == 24:
            return base_date.replace(hour=0, minute=minute) + timedelta(days=1)
        return base_date.replace(hour=hour, minute=minute)

    def _parse_usage_value(self, raw_value: str) -> float | None:
        normalized = raw_value.strip().replace(",", "")
        if not normalized or normalized in {"-", "--"}:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
