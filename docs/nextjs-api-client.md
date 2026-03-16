# Next.js API Client

`[nextjs-api-client.ts](/Users/jagashira/work/github.com/Jagashira/home-billing-api/docs/nextjs-api-client.ts)` は `home-billing-api` を Next.js から呼ぶための型定義と fetch 関数のサンプルです。

## 想定 env

```env
NEXT_PUBLIC_HOME_BILLING_API_URL=http://192.168.11.12:8000
```

## 使い方

```ts
import {
  fetchElectricityUsageSummary,
  fetchElectricityUsageTimeSeries,
  fetchElectricityUsageMonths,
} from "@/lib/home-billing-api";

const months = await fetchElectricityUsageMonths({
  providerName: "hepco_electricity",
});

const latestMonth = months.items[0]?.billing_month;

if (latestMonth) {
  const summary = await fetchElectricityUsageSummary({
    providerName: "hepco_electricity",
    billingMonth: latestMonth,
  });

  const timeseries = await fetchElectricityUsageTimeSeries({
    providerName: "hepco_electricity",
    billingMonth: latestMonth,
  });
}
```

## おすすめ利用先

- 月一覧: `fetchElectricityUsageMonths`
- 上部サマリーカード: `fetchElectricityUsageSummary`
- 折れ線グラフ: `fetchElectricityUsageTimeSeries`
- CSV ダウンロードリンク: `buildElectricityUsageCsvUrl`
- SoftBank 手動取得ボタン: `runSoftbankInternetFetch`
- HEPCO 手動取得ボタン: `runHepcoElectricityFetch`
