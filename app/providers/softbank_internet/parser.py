from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from app.providers.base.errors import ErrorCode, ProviderError
from app.providers.base.interfaces import BillingSummaryItem, Parser, ProviderFetchPayload, ProviderFetchResult
from app.providers.softbank_internet.utils import normalize_amount_to_yen


logger = logging.getLogger(__name__)


class SoftbankBillingParser(Parser):
    def parse(self, payload: ProviderFetchPayload) -> ProviderFetchResult:
        soup = BeautifulSoup(payload.html, "html.parser")
        try:
            account_id = self._parse_account_id(soup)
            billing_items = self._parse_all_billing_summaries(soup, payload.source_url)
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
                }
                for item in billing_items
            ],
        }
        logger.info("SoftBank billing page parsed successfully.")
        return ProviderFetchResult(
            service_type="internet",
            provider_name="softbank_internet",
            account_id=account_id,
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

    def _parse_all_billing_summaries(
        self,
        soup: BeautifulSoup,
        source_url: str,
    ) -> list[BillingSummaryItem]:
        items: list[BillingSummaryItem] = []
        containers = soup.select("div.touch-contents-wrap.less-border")
        for container in containers:
            month_node = container.select_one("p.p-top-10 span.fs-16")
            amount_node = container.select_one("p.right.m-bottom-0 span.fs-24")
            if not month_node or not amount_node:
                continue

            month_text = month_node.get_text(strip=True)
            month_match = self._find_month_pattern(month_text)
            if not month_match:
                continue

            grid_rows = container.select(".grid-arr.t-1.col-2.m-bottom-0")
            usage_period = self._extract_usage_period(grid_rows)
            payment_status = self._extract_payment_status(grid_rows)
            detail_link = container.select_one('a[href*="chargedetail"]')
            detail_url = None
            if detail_link and detail_link.get("href"):
                detail_url = self._build_detail_url(source_url, str(detail_link.get("href")))

            items.append(
                BillingSummaryItem(
                    billing_month=month_match,
                    total_amount=normalize_amount_to_yen(amount_node.get_text(strip=True)),
                    currency="JPY",
                    usage_period=usage_period,
                    payment_status=payment_status,
                    detail_url=detail_url,
                )
            )

        if items:
            return items

        billing_month = self._parse_billing_month(soup)
        total_amount = self._parse_total_amount(soup)
        return [
            BillingSummaryItem(
                billing_month=billing_month,
                total_amount=total_amount,
                currency="JPY",
            )
        ]

    def _parse_total_amount(self, soup: BeautifulSoup) -> int:
        selector_candidates = [
            "#total-amount",
            ".billing-total .amount",
            "p.right.m-bottom-0 span.fs-24",
            ".grid-arr .fs-24",
            '[data-testid="billing-total-amount"]',
        ]
        for selector in selector_candidates:
            node = soup.select_one(selector)
            if node and node.get_text(strip=True):
                return normalize_amount_to_yen(node.get_text(strip=True))

        text_match = self._find_value_from_label(soup, ["ご請求金額", "請求金額", "合計金額", "合計"])
        if text_match:
            return normalize_amount_to_yen(text_match)

        raise ProviderError(
            ErrorCode.PARSE_FAILED,
            "Failed to locate total billing amount. Update selector candidates or label search rules.",
        )

    def _parse_billing_month(self, soup: BeautifulSoup) -> str:
        text_match = self._find_value_from_label(
            soup,
            ["請求月", "ご利用月", "対象月", "請求年月", "利用年月", "ご請求月"],
        )
        if text_match:
            month_match = self._find_month_pattern(text_match)
            if month_match:
                return month_match

        selector_candidates = [
            "#billing-month",
            ".billing-month",
            ".month",
            ".ym",
            "p.p-top-10 span.fs-16",
            ".grid-arr .unit.w-45 .fs-16",
            '[data-testid="billing-month"]',
        ]
        for selector in selector_candidates:
            node = soup.select_one(selector)
            if node and node.get_text(strip=True):
                month_match = self._find_month_pattern(node.get_text(strip=True))
                if month_match:
                    return month_match

        for text in soup.stripped_strings:
            month_match = self._find_month_pattern(text)
            if month_match:
                return month_match

        raise ProviderError(
            ErrorCode.REQUIRED_FIELD_MISSING,
            "Billing month is missing. Update parser rules for the current SoftBank page.",
        )

    def _parse_account_id(self, soup: BeautifulSoup) -> str:
        text_match = self._find_value_from_label(
            soup,
            ["S-ID", "アカウント", "契約番号", "カスタマーID", "customer_id"],
        )
        if text_match:
            return text_match.strip()

        selector_candidates = [
            "#account-id",
            ".account-id",
            'input[title="customer_id"]',
            ".sba-identity",
            '[data-testid="account-id"]',
        ]
        for selector in selector_candidates:
            node = soup.select_one(selector)
            if node:
                if node.get("value"):
                    return str(node.get("value")).strip()
                if node.get_text(strip=True):
                    return node.get_text(strip=True)

        raise ProviderError(
            ErrorCode.REQUIRED_FIELD_MISSING,
            "Account ID is missing from the fetched page. Update account selectors or label extraction.",
        )

    def _find_value_from_label(self, soup: BeautifulSoup, labels: list[str]) -> str | None:
        normalized_texts = list(soup.stripped_strings)
        for index, text in enumerate(normalized_texts):
            if any(label in text for label in labels):
                if "：" in text:
                    left, _, right = text.partition("：")
                    if right.strip():
                        return right.strip()
                if ":" in text:
                    left, _, right = text.partition(":")
                    if right.strip():
                        return right.strip()
                if index + 1 < len(normalized_texts):
                    return normalized_texts[index + 1]
        return None

    def _find_month_pattern(self, text: str) -> str | None:
        patterns = [
            r"(\d{4}年\d{1,2}月分)",
            r"(\d{4}年\d{1,2}月)",
            r"(\d{4}[/-]\d{1,2})",
            r"(\d{1,2}月分)",
            r"(\d{1,2}月)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def _build_detail_url(self, source_url: str, href: str) -> str:
        if href.startswith("http://") or href.startswith("https://"):
            return href
        match = re.match(r"^(https?://[^/]+)", source_url)
        if not match:
            return href
        return f"{match.group(1)}{href}"

    def _extract_usage_period(self, grid_rows: list[BeautifulSoup]) -> str | None:
        if len(grid_rows) < 2:
            return None
        units = grid_rows[1].find_all("div", recursive=False)
        if not units:
            return None
        text = units[0].get_text(" ", strip=True)
        if text and "ご使用分" in text:
            return text
        return None

    def _extract_payment_status(self, grid_rows: list[BeautifulSoup]) -> str | None:
        if len(grid_rows) < 2:
            return None
        units = grid_rows[1].find_all("div", recursive=False)
        if len(units) < 2:
            return None
        text = units[1].get_text(" ", strip=True)
        return text or None
