# home-utility-api

`home-utility-api` は、自宅サーバー上で各種インフラサービスの料金情報を取得・保存・参照するための FastAPI ベースの API です。現状は SoftBank のインターネット料金と、HEPCO ポータルの電気料金および 30 分電力量 CSV を取得できます。

## 対応範囲

- provider 追加型のプロジェクト構成
- SoftBank internet provider
- HEPCO electricity provider
- Playwright を使ったログイン処理の土台
- 対象ページ取得処理の土台
- SQLite への請求情報・fetch ログ保存
- FastAPI による API 提供
- 手動 fetch 実行 API
- ログとエラー保存

## ディレクトリ構成

```text
home-utility-api/
  app/
    api/
    models/
    providers/
      base/
      softbank_internet/
    schemas/
    services/
  logs/
  data/
  alembic/
  scripts/
  snapshots/
  tests/
```

## セットアップ

### 1. 仮想環境を作成

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2. 依存をインストール

```bash
pip install -r requirements.txt
```

### 3. Playwright のブラウザをインストール

```bash
playwright install chromium
```

### 4. `.env` を作成

`.env.example` をコピーして `.env` を作成し、必要な値を設定してください。

```bash
cp .env.example .env
```

設定項目:

- `SOFTBANK_SID`
- `SOFTBANK_PASSWORD`
- `SOFTBANK_LOGIN_URL`
- `SOFTBANK_TARGET_URL`
- `HEPCO_LOGIN_ID`
- `HEPCO_PASSWORD`
- `HEPCO_LOGIN_URL`
- `HEPCO_TARGET_URL`
- `DATABASE_URL`
- `LOG_LEVEL`
- `HEADLESS`

home-server で Docker 運用する場合、`DATABASE_URL` はこれに揃えてください。

```env
DATABASE_URL=sqlite:////app/data/home_utility.db
```

## 起動方法

### DB 初期化

```bash
python -m scripts.init_db
```

このスクリプトは Alembic の `upgrade head` を実行します。

### API 起動

```bash
python -m scripts.init_db
uvicorn app.main:app --reload
```

### Mac でローカル実行

初回セットアップ:

```bash
./scripts/setup_local_mac.sh
```

起動:

```bash
./scripts/run_local.sh
```

既定では `0.0.0.0:8000` で待ち受けます。必要なら `HOST` と `PORT` を上書きしてください。

### Docker で起動

```bash
docker compose up --build
```

初回は Playwright 用のイメージビルドに少し時間がかかります。
`data/` をマウントしているので SQLite ファイルはホスト側にも残ります。

`docker compose` が使えない環境では、次でも同じ構成で動かせます。

```bash
docker build -t home-billing-api .
docker run --name home-billing-api \
  -p 8000:8000 \
  --env-file .env \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/snapshots:/app/snapshots" \
  -v "$(pwd)/data:/app/data" \
  home-billing-api
```

### Docker を使わずに起動

```bash
uvicorn app.main:app --reload
```

## 手動 fetch 実行

### API 経由

```bash
curl -X POST http://127.0.0.1:8000/api/fetch/softbank_internet
curl -X POST http://127.0.0.1:8000/api/fetch/hepco_electricity
```

### スクリプト経由

```bash
python -m scripts.run_fetch softbank_internet
python -m scripts.run_fetch hepco_electricity
```

### Docker コンテナ内で実行

```bash
docker compose exec api python -m scripts.run_fetch softbank_internet
docker compose exec api python -m scripts.run_fetch hepco_electricity
```

## DB を見る

SQLite CLI を使うのが一番簡単です。

```bash
sqlite3 data/home_utility.db
```

よく使う確認コマンド:

```sql
.tables
.schema billing_records
SELECT provider_name, account_id, billing_month, total_amount, usage_period, payment_status
FROM billing_records
ORDER BY billing_month DESC;

SELECT provider_name, account_id, billing_month, measured_at, usage_kwh
FROM electricity_usage_records
ORDER BY measured_at DESC
LIMIT 20;
```

## Alembic

スキーマ変更は Alembic で管理します。

現在の migration を適用:

```bash
python -m scripts.init_db
```

直接実行する場合:

```bash
alembic upgrade head
```

新しい migration を追加する場合:

```bash
alembic revision -m "add new column"
```

## Home-Server 運用例

### systemd から Docker を起動する例

```ini
[Unit]
Description=home-billing-api
After=docker.service
Requires=docker.service

[Service]
Restart=always
WorkingDirectory=/opt/home-billing-api
ExecStart=/usr/bin/docker compose up
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

### cron で手動 fetch API を定期実行する例

毎日 06:00 に fetch:

```cron
0 6 * * * curl -fsS -X POST http://127.0.0.1:8000/api/fetch/softbank_internet >/dev/null
```

## API エンドポイント

- `GET /health`
- `GET /api/providers`
- `GET /api/billing/latest`
- `GET /api/billing/latest/internet`
- `GET /api/billing/latest/electricity`
- `GET /api/billing/history`
- `GET /api/usage/electricity`
- `GET /api/usage/electricity/months`
- `GET /api/usage/electricity/csv?billing_month=2026年2月分`
- `POST /api/fetch/softbank_internet`
- `POST /api/fetch/hepco_electricity`
- `GET /api/fetch/status`

## テスト

```bash
pytest
```

## 今後の拡張予定

- `tokyo_gas` provider の追加
- スケジューラによる定期 fetch
- parser の DOM 追従強化
- 認証フローやセッション更新の provider 別最適化

## 注意事項

- スクレイピング先の画面変更により parser や selector は壊れる可能性があります。
- 実運用資格情報は絶対にコミットしないでください。
- SoftBank のログイン selector と DOM は仮置きです。`app/providers/softbank_internet/` 配下の TODO を起点に差し替えてください。
- HEPCO のログイン selector と DOM は実ページに合わせた初期候補です。`app/providers/hepco_electricity/` 配下の selector 候補を必要に応じて調整してください。
- 現在のログイン開始 URL は `SOFTBANK_LOGIN_URL` で差し替え可能です。既定の想定 URL は `https://bbss.softbankbb.co.jp/AUT/ftth?mem=memCertAFsd&.func=myPage` です。
- `HEPCO_LOGIN_URL` の既定値は `https://www.epower-portal.com/hepco` です。
- `billing_records` は月単位で保存し、同じ `provider_name + account_id + service_type + billing_month` が既にあれば保存をスキップします。
- `electricity_usage_records` は 30 分単位で保存し、同じ `provider_name + account_id + measured_at` が既にあれば保存をスキップします。
- parser を更新しても既存の月レコードは重複スキップされるため、抽出結果を作り直したい場合は対象 DB を退避または再作成してください。
