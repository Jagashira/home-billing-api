from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    display_name: str
    service_type: str
    description: str


@dataclass(frozen=True)
class ProviderConfig:
    headless: bool
    login_url: str
    target_url: str
    username: str
    password: str


@dataclass(frozen=True)
class ProviderFetchContext:
    snapshots_dir: Path
    run_started_at: datetime


@dataclass(frozen=True)
class ProviderFetchPayload:
    html: str
    source_url: str
    html_snapshot_path: str | None
    screenshot_path: str | None


@dataclass(frozen=True)
class BillingSummaryItem:
    billing_month: str
    total_amount: int
    currency: str
    usage_period: str | None = None
    payment_status: str | None = None
    detail_url: str | None = None


@dataclass(frozen=True)
class ProviderFetchResult:
    service_type: str
    provider_name: str
    account_id: str
    billing_month: str
    total_amount: int
    currency: str
    fetched_at: datetime
    source_url: str
    status: str
    billing_items: list[BillingSummaryItem] | None = None
    raw_data_json: str | None = None
    raw_snapshot_path: str | None = None
    screenshot_path: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class PersistResult:
    latest_record: ProviderFetchResult | None
    saved_count: int
    skipped_count: int


class Authenticator(ABC):
    @abstractmethod
    def login(self, page: Any, config: ProviderConfig, context: ProviderFetchContext) -> None:
        raise NotImplementedError


class Fetcher(ABC):
    @abstractmethod
    def fetch(self, config: ProviderConfig, context: ProviderFetchContext) -> ProviderFetchPayload:
        raise NotImplementedError


class Parser(ABC):
    @abstractmethod
    def parse(self, payload: ProviderFetchPayload) -> ProviderFetchResult:
        raise NotImplementedError


class Provider(ABC):
    metadata: ProviderMetadata

    @abstractmethod
    def is_enabled(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch_billing(self, context: ProviderFetchContext) -> ProviderFetchResult:
        raise NotImplementedError
