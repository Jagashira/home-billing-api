export type ProviderInfo = {
  name: string;
  display_name: string;
  service_type: string;
  enabled: boolean;
  description: string;
};

export type BillingRecord = {
  id: number;
  service_type: string;
  provider_name: string;
  account_id: string;
  billing_month: string;
  total_amount: number;
  currency: string;
  usage_period: string | null;
  payment_status: string | null;
  detail_url: string | null;
  fetched_at: string;
  source_url: string;
  status: string;
  raw_data_json: string | null;
  raw_snapshot_path: string | null;
  screenshot_path: string | null;
  error_message: string | null;
};

export type BillingHistoryResponse = {
  items: BillingRecord[];
};

export type BillingSummaryItem = {
  billing_month: string;
  total_amount: number;
  currency: string;
  usage_period: string | null;
  payment_status: string | null;
  detail_url: string | null;
  pdf_url: string | null;
  csv_url: string | null;
  csv_path: string | null;
  usage_row_count: number | null;
};

export type UsageFile = {
  billing_month: string;
  csv_url: string;
  csv_path: string | null;
  row_count: number;
};

export type FetchExecutionResponse = {
  provider_name: string;
  success: boolean;
  message: string;
  billing_record_id: number | null;
  saved_count: number;
  skipped_count: number;
  account_id: string | null;
  billing_month: string | null;
  total_amount: number | null;
  currency: string | null;
  status: string | null;
  billing_items: BillingSummaryItem[] | null;
  usage_saved_count: number;
  usage_skipped_count: number;
  usage_files: UsageFile[] | null;
  error_code: string | null;
  error_message: string | null;
  screenshot_path: string | null;
  html_snapshot_path: string | null;
};

export type FetchStatus = {
  provider_name: string;
  started_at: string;
  finished_at: string | null;
  success: boolean;
  error_code: string | null;
  error_message: string | null;
  screenshot_path: string | null;
  html_snapshot_path: string | null;
} | null;

export type ElectricityUsageRecord = {
  id: number;
  provider_name: string;
  account_id: string;
  billing_month: string;
  measured_at: string;
  usage_kwh: number;
  source_url: string | null;
  csv_path: string | null;
};

export type ElectricityUsageHistoryResponse = {
  items: ElectricityUsageRecord[];
};

export type ElectricityUsageMonthSummary = {
  provider_name: string;
  account_id: string;
  billing_month: string;
  row_count: number;
  first_measured_at: string | null;
  last_measured_at: string | null;
  csv_path: string | null;
  source_url: string | null;
};

export type ElectricityUsageMonthSummaryResponse = {
  items: ElectricityUsageMonthSummary[];
};

export type ElectricityUsagePoint = {
  measured_at: string;
  usage_kwh: number;
};

export type ElectricityUsageTimeSeriesResponse = {
  provider_name: string;
  account_id: string | null;
  billing_month: string;
  points: ElectricityUsagePoint[];
};

export type ElectricityUsageSummary = {
  provider_name: string;
  account_id: string | null;
  billing_month: string;
  point_count: number;
  total_usage_kwh: number;
  average_usage_kwh: number;
  min_usage_kwh: number | null;
  max_usage_kwh: number | null;
  first_measured_at: string | null;
  last_measured_at: string | null;
};

export type ElectricityUsageDailyPoint = {
  date: string;
  usage_kwh: number;
};

export type ElectricityUsageDailyResponse = {
  provider_name: string;
  account_id: string | null;
  billing_month: string;
  days: ElectricityUsageDailyPoint[];
};

export type ElectricityUsageHourlyPoint = {
  slot: string;
  usage_kwh: number;
  average_usage_kwh: number;
};

export type ElectricityUsageHourlyResponse = {
  provider_name: string;
  account_id: string | null;
  billing_month: string;
  hours: ElectricityUsageHourlyPoint[];
};

type RequestOptions = {
  baseUrl?: string;
  init?: RequestInit;
};

type UsageQuery = {
  providerName?: string;
  accountId?: string;
  billingMonth?: string;
};

function buildUrl(path: string, baseUrl: string, query?: Record<string, string | number | undefined>) {
  const url = new URL(path, baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }
  }
  return url.toString();
}

async function getJson<T>(path: string, options: RequestOptions = {}, query?: Record<string, string | number | undefined>): Promise<T> {
  const baseUrl = options.baseUrl ?? process.env.NEXT_PUBLIC_HOME_BILLING_API_URL ?? "http://localhost:8000";
  const response = await fetch(buildUrl(path, baseUrl, query), {
    ...options.init,
    headers: {
      Accept: "application/json",
      ...(options.init?.headers ?? {}),
    },
    cache: options.init?.cache ?? "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
}

async function postJson<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const baseUrl = options.baseUrl ?? process.env.NEXT_PUBLIC_HOME_BILLING_API_URL ?? "http://localhost:8000";
  const response = await fetch(buildUrl(path, baseUrl), {
    method: "POST",
    ...options.init,
    headers: {
      Accept: "application/json",
      ...(options.init?.headers ?? {}),
    },
    cache: options.init?.cache ?? "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return (await response.json()) as T;
}

export async function fetchHealth(options?: RequestOptions): Promise<{ status: string }> {
  return getJson("/health", options);
}

export async function fetchProviders(options?: RequestOptions): Promise<ProviderInfo[]> {
  return getJson("/api/providers", options);
}

export async function fetchLatestBilling(options?: RequestOptions): Promise<BillingRecord[]> {
  return getJson("/api/billing/latest", options);
}

export async function fetchLatestInternetBilling(options?: RequestOptions): Promise<BillingRecord[]> {
  return getJson("/api/billing/latest/internet", options);
}

export async function fetchLatestElectricityBilling(options?: RequestOptions): Promise<BillingRecord[]> {
  return getJson("/api/billing/latest/electricity", options);
}

export async function fetchBillingHistory(
  params: {
    providerName?: string;
    serviceType?: string;
    limit?: number;
  } = {},
  options?: RequestOptions,
): Promise<BillingHistoryResponse> {
  return getJson("/api/billing/history", options, {
    provider_name: params.providerName,
    service_type: params.serviceType,
    limit: params.limit,
  });
}

export async function runSoftbankInternetFetch(options?: RequestOptions): Promise<FetchExecutionResponse> {
  return postJson("/api/fetch/softbank_internet", options);
}

export async function runHepcoElectricityFetch(options?: RequestOptions): Promise<FetchExecutionResponse> {
  return postJson("/api/fetch/hepco_electricity", options);
}

export async function fetchLatestFetchStatus(options?: RequestOptions): Promise<FetchStatus> {
  return getJson("/api/fetch/status", options);
}

export async function fetchElectricityUsage(
  params: UsageQuery & { limit?: number } = {},
  options?: RequestOptions,
): Promise<ElectricityUsageHistoryResponse> {
  return getJson("/api/usage/electricity", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
    limit: params.limit,
  });
}

export async function fetchElectricityUsageMonths(
  params: Omit<UsageQuery, "billingMonth"> & { limit?: number } = {},
  options?: RequestOptions,
): Promise<ElectricityUsageMonthSummaryResponse> {
  return getJson("/api/usage/electricity/months", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    limit: params.limit,
  });
}

export async function fetchElectricityUsageTimeSeries(
  params: UsageQuery & { billingMonth: string },
  options?: RequestOptions,
): Promise<ElectricityUsageTimeSeriesResponse> {
  return getJson("/api/usage/electricity/timeseries", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
  });
}

export async function fetchElectricityUsageSummary(
  params: UsageQuery & { billingMonth: string },
  options?: RequestOptions,
): Promise<ElectricityUsageSummary> {
  return getJson("/api/usage/electricity/summary", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
  });
}

export async function fetchElectricityUsageDaily(
  params: UsageQuery & { billingMonth: string },
  options?: RequestOptions,
): Promise<ElectricityUsageDailyResponse> {
  return getJson("/api/usage/electricity/daily", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
  });
}

export async function fetchElectricityUsageHourly(
  params: UsageQuery & { billingMonth: string },
  options?: RequestOptions,
): Promise<ElectricityUsageHourlyResponse> {
  return getJson("/api/usage/electricity/hourly", options, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
  });
}

export function buildElectricityUsageCsvUrl(
  params: UsageQuery & { billingMonth: string },
  baseUrl = process.env.NEXT_PUBLIC_HOME_BILLING_API_URL ?? "http://localhost:8000",
): string {
  return buildUrl("/api/usage/electricity/csv", baseUrl, {
    provider_name: params.providerName,
    account_id: params.accountId,
    billing_month: params.billingMonth,
  });
}
