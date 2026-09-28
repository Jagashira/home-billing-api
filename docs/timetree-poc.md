# TimeTree Web Playwright PoC

## 目的と確認済み範囲

このPoCは、既存の `api` コンテナに含まれる Playwright / Chromium を再利用し、TimeTree Webをブラウザとして操作できるかを確認するためのものです。Google Calendar連携、同期DB、定期実行、双方向同期は含みません。TimeTreeの非公開APIも使用しません。

2026-09-27時点で、公式Web版URL `https://timetreeapp.com/signin` がChromiumで開けること、認証済みカレンダー画面、カレンダー一覧、新規予定フォームを実アカウントで読み取り専用確認しています。予定詳細URLは `/calendars/:aliasCode/events/:eventId` で、所有台帳はこの形のHTTPS URLだけを受理します。実イベントの保存・更新・削除はまだ実行していません。DOMが確認済みの形と異なる場合、PoCはスクリーンショットを保存して失敗し、成功扱いにはしません。

## リポジトリ調査結果

- 親 `compose.yml` には `home-dashboard`、`api`、`immich-server`、`immich-postgres`、`immich-redis`、`smb` があり、`api` は `/data` をホストの `./data` へbind mountしています。
- `api` は `mcr.microsoft.com/playwright/python:v1.46.0-jammy` と `playwright==1.46.0` をすでに使っています。既存providerも同期PlaywrightでChromiumを起動しているため、同じ基盤を再利用できます。
- 既存の共通ログは `/app/logs`、snapshotは `/app/snapshots` が既定で、親Composeでは永続化されません。このPoC固有のログと成果物は永続化済みの `/data/timetree` へ置きます。
- 親の `data/*` はGit除外済みで、バックアップ処理は `data/` 全体を対象にしています。アプリ単独実行時の認証状態も追加の `.gitignore` / `.dockerignore` で除外します。
- 既存 `api` コンテナで必要条件を満たせるため、独立サービスを追加する運用上の利点はありません。

TimeTree公式ヘルプでも、[Web版へのログイン](https://support.timetreeapp.com/hc/ja/articles/360000238862-PC-%E3%82%BF%E3%83%96%E3%83%AC%E3%83%83%E3%83%88%E3%81%A7%E3%82%82%E4%BD%BF%E3%81%84%E3%81%9F%E3%81%84-Web%E7%89%88)と[Web版での予定作成](https://support.timetreeapp.com/hc/en-us/articles/206212261-I-want-to-know-TimeTree-Web-functions)、[予定の編集・削除](https://support.timetreeapp.com/hc/en-us/articles/205198555-How-to-copy-edit-delete-events)が案内されています。

## 配置と永続データ

新しいサービスは追加しません。`apps/home-billing-api/app/timetree/` を既存 `api` コンテナ内で実行します。親 `compose.yml` はすでに `./data:/data` をマウントしているため、既定の `/data/timetree` はホストの `data/timetree` に永続化されます。

```text
data/timetree/
├── auth/storage-state.json   # ログイン状態。秘密情報として扱う
├── auth/session.json         # 実際に確認した認証済み開始URL
├── owned-events.json         # PoCが所有するイベントの台帳
├── pending-creates.json      # 保存開始後、URL確定前の安全な照合情報
├── logs/timetree.log
├── artifacts/                # エラー画像、メタデータ、probe結果
└── traces/                   # --debug 時のPlaywright trace
```

各ディレクトリはモード `0700`、認証状態・台帳・ログ・成果物は可能な範囲で `0600` にします。親リポジトリの `data/*` と、このアプリを単独実行する場合の `data/timetree/` / `timetree-local/` はGit管理対象外です。

## 設定

`apps/home-billing-api/.env` に対象カレンダーの完全一致名だけを設定します。メールアドレスやパスワードは書きません。

```env
TIMETREE_CALENDAR_NAME=彼女との共有カレンダー名
TIMETREE_DATA_DIR=/data/timetree
TIMETREE_HEADLESS=true
TIMETREE_DEBUG=false
TIMETREE_TIMEOUT_MS=30000
```

対象名が空、見つからない、または同名候補が複数ある場合、作成は拒否されます。

## 初回ログイン

Home ServerへVNC/noVNCを常設すると、追加コンテナ、公開ポート、認証、更新対象が増えます。このPoCでは、GUIのある信頼済みMac等で人間が正規ログインし、Playwrightのstorage stateだけを暗号化されたSSH経由でサーバーへ移します。CAPTCHAや2FAは人間が通常どおり完了し、PoCは回避しません。

Mac側で、このAPIリポジトリとPython 3.11を用意します。

```bash
cd apps/home-billing-api
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m app.timetree --data-dir ./timetree-local login
```

Chromiumでログインが完了すると `timetree-local/auth/storage-state.json` と `session.json` が作られます。後者には初回ログインで実在を確認した認証済みURLを保存し、再起動後の認証確認開始点に使います。ブラウザのパスワード保存は使わず、認証操作は人間が行います。

ログイン待機にはPythonの`time.sleep()`を使わず、Playwright自身の短い待機を使います。これにより、人間の操作中もPlaywrightのnavigation、popup、新規tab、page closeイベントが処理され、`context.pages`と各`Page.url`が更新されます。認証済みpageは同じBrowserContext内の全pageから探します。`/signin`、`/intl/ja`、外部origin、認証済み根拠のない公開ページは成功扱いにしません。`/calendars/<id>`等のアプリrouteでもログインフォームが見えている場合は拒否します。

`--debug`では、Cookie、localStorage、フォーム内容を出力せず、page数、query/fragmentを除いた各page URL、認証判定理由、page open/navigation/closeをログへ記録します。ログインが完了しない場合は、まず次を確認してください。

```bash
tail -f timetree-local/logs/timetree.log
```

TimeTreeは`domcontentloaded`後も`#react-root`内に`.loading`を表示し、React UIを遅れて描画します。認証済みrouteへの移動では、実artifactで確認したこのloading表示が消え、アプリshell内にlink、button、input等の操作要素が出るまで`TIMETREE_TIMEOUT_MS`内で待ちます。`networkidle`や長い固定sleepには依存しません。timeout時は空のprobeを成功扱いにせず、診断値と失敗artifactを保存します。

アプリshellが操作可能になった後も、Calendar Listの行は遅れて描画される場合があります。対象名が最初の読取りで見つからない場合は、確認済みのcanonical calendar linkまたは「Show only this calendar」を持つsemantic rowに完全一致名が現れるまでbounded waitし、DOMを再読取りします。対象が0件のまま、同名が複数、または別カレンダーの現在URLしか確認できない場合は拒否します。対象名を一意に検出した後は、`/calendars/<id>`上でタイトルとURLの組み合わせが一致するまで既存のbounded waitを使い、そのURLを`CalendarInfo`へ保存します。URLが取得できず、現在ページも対象と確認できない場合は見出しをクリックしません。

debugログの`TIMETREE_PAGE_DIAGNOSTICS`には、`document.readyState`、query/fragmentを除いたURL、操作要素数、body textの文字数、calendar link候補数、page titleだけを記録します。body textや予定名そのものはログへ出しません。probeのprivate artifactには各操作要素のrole、accessible name相当の属性、可視状態を保存します。

次に、MacからHome Serverへ転送します。サーバー上の実配置が `/home/home-server/home-platform` の場合は次のとおりです。

```bash
ssh home-server 'mkdir -p /home/home-server/home-platform/data/timetree/auth && chmod 700 /home/home-server/home-platform/data/timetree /home/home-server/home-platform/data/timetree/auth'
scp ./timetree-local/auth/storage-state.json ./timetree-local/auth/session.json home-server:/home/home-server/home-platform/data/timetree/auth/
ssh home-server 'chmod 600 /home/home-server/home-platform/data/timetree/auth/storage-state.json /home/home-server/home-platform/data/timetree/auth/session.json'
```

storage stateはログイン可能な秘密情報です。チャット、メール、共有フォルダへ置かないでください。TimeTree側が端末移送したセッションを受け付けない場合は、storage state方式では成立しません。その場合だけ、SSHトンネル内に限定した一時noVNCを別PoCとして検討します。このリポジトリには常設VNCを追加していません。

## Home Serverでの起動と安全な検証順序

以下は親リポジトリ `/home/home-server/home-platform` で実行します。

```bash
docker compose build api
docker compose up -d api
docker compose exec api python -m app.timetree status
docker compose exec api python -m app.timetree calendars
docker compose exec api python -m app.timetree --debug probe
docker compose exec api python -m app.timetree --debug probe --surface create
docker compose exec api python -m app.timetree --debug probe --surface create-filled --date 2026-09-28
```

`status` が `authenticated: true`、`calendars` に設定した共有カレンダーが完全一致で1件だけ表示されることを確認します。認証判定はfail-closedで、ログイン欄が見えないだけでは成功にせず、カレンダーアプリのURLまたはカレンダーリンクが実在することを要求します。`probe` は現在画面のスクリーンショットと、操作可能要素のrole、accessible name相当の属性、リンクを保存します。`--surface create` は対象カレンダーの新規予定フォームを開きますが、入力も保存も行いません。

`--surface create-filled`は、PoCタイトル、指定日、19:00–20:00、所有確認用Noteを通常のPlaywright操作で入力し、各値、`aria-invalid`、validation message、Saveのenabled状態を読み戻します。Noteモーダルの`OK`は押しますが、予定フォームのSaveは絶対に押しません。日付はTimeTreeが受理する表示形式で入力し、読み戻した値をdate-onlyのISO形式へ正規化して照合します。個人の予定名を含む可能性があるのでartifactは外部共有しないでください。

### 1. dry-run

変更系コマンドは、`--apply` を付けなければ保存、更新、削除ボタンを押しません。

```bash
docker compose exec api python -m app.timetree create-test --date 2026-09-23
docker compose exec api python -m app.timetree update-test
docker compose exec api python -m app.timetree delete-test
docker compose exec api python -m app.timetree cleanup-test
```

createのdry-runは対象カレンダーを完全一致で解決し、生成予定の一意なタイトルをログへ出すところで終了します。update/deleteのdry-runは所有台帳のイベントURLを直接開き、イベントID、完全一致タイトル、所有トークンを確認した後で終了します。

### 2. 作成

画面と `probe` 結果を確認した後に、PoCイベントを1件だけ作成します。

```bash
docker compose exec api python -m app.timetree create-test --date 2026-09-23 --apply
docker compose exec api python -m app.timetree records
docker compose exec api python -m app.timetree --debug probe --surface owned --record-id RECORD_ID
```

タイトル例:

```text
[HOME-SERVER-POC] TimeTree Sync Test [HSP-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx]
```

保存ボタンを押す直前に、タイトル、所有トークン、日付、カレンダー名を `pending-creates.json` へ記録します。保存後、TimeTreeの確認済み予定詳細URL形式、完全一致タイトル、所有トークンを確認できた場合だけ `owned-events.json` に移して成功とします。クエリ文字列や似たパスからイベントIDを推測しません。イベントID付きURLを取得できない場合は成功扱いにせず、pending情報とエラー成果物を残すため、人間がTimeTree画面上の完全一致トークンを確認できます。

保存後のURL解決時にTimeTreeのrelease announcement cardが表示されている場合は、そのcard内にある専用の `data-test-id="release-announcement-card--close"` が一意であることを確認して1回だけ閉じます。汎用のClose、複数候補、可視状態が矛盾する候補は操作しません。URL解決に失敗してもCREATEを再実行せず、pending情報を残します。

UPDATE/DELETEの所有確認では、event detail routeのアプリshellだけで判定を始めません。実DOMで確認した `h1[data-test-id="event-title"]` が可視かつ一意で、保存済みPoC titleと完全一致するまでbounded waitします。その後もevent ID、完全一致title、ownership tokenを既存のownership検証で再確認します。部分一致やtoken単独では通過しません。

UPDATEのEdit画面では、CREATEと同じ `textarea[name="title"][placeholder="Event title (required)"]` が可視かつ一意になり、現在値が台帳の保存済みtitleと完全一致するまでbounded waitします。別のinputや汎用textareaへfallbackしません。新しいtitleを入力した後もPoC prefixとownership tokenを含む完全な値を再確認してから、Saveを1回だけ押します。

### 3. 更新

まずdry-run、次に `--apply` の順で実行します。activeレコードが複数ある場合は `records` で確認した `--record-id` が必須です。

```bash
docker compose exec api python -m app.timetree update-test --record-id RECORD_ID
docker compose exec api python -m app.timetree update-test --record-id RECORD_ID --apply
```

更新後のタイトルにも同じPoC接頭辞と所有トークンを強制します。保存後は台帳の予定詳細URLを開き直し、新タイトルと所有トークンを確認してから台帳を更新します。

### 4. 削除

削除は復元できません。PoCは台帳のイベントURLへ直接移動し、イベントID、完全一致タイトル、所有トークンが一致した場合だけ削除メニューを開きます。削除後は同じURLを開き直し、タイトルと所有トークンが存在しないことを確認してから台帳を削除済みにします。

```bash
docker compose exec api python -m app.timetree delete-test --record-id RECORD_ID
docker compose exec api python -m app.timetree delete-test --record-id RECORD_ID --apply
```

`cleanup-test` も台帳内のactiveなPoCイベントだけが対象で、既定上限は10件、最大20件です。

```bash
docker compose exec api python -m app.timetree cleanup-test
docker compose exec api python -m app.timetree cleanup-test --limit 10 --apply
```

### Pending create台帳だけを整理する

Save失敗後に残ったpending recordは、TimeTreeへアクセスしない専用コマンドで1件ずつ整理します。`cleanup-test`とは別機能で、完全一致するownership tokenがちょうど1件の場合だけ対象になります。既定はdry-runです。

```bash
python -m app.timetree --data-dir ./timetree-local pending-cleanup \
  --ownership-token HSP-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

TimeTree上に同じtokenのイベントが存在しないことを人間が確認した後だけ、`--apply`を付けます。

```bash
python -m app.timetree --data-dir ./timetree-local pending-cleanup \
  --ownership-token HSP-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx \
  --apply
```

このコマンドはブラウザとPlaywrightを起動せず、`pending-creates.json`だけをatomic replaceで更新します。`owned-events.json`、storage state、session、TimeTree上の予定には触れません。tokenが0件または重複している場合は変更せず失敗します。

## ログ、スクリーンショット、HTML、trace

コンテナログには次の識別子を出します。

- `TIMETREE_NAVIGATE`
- `TIMETREE_AUTH_OK`
- `TIMETREE_AUTH_REQUIRED`
- `TIMETREE_CALENDAR_FOUND`
- `TIMETREE_EVENT_CREATED`
- `TIMETREE_EVENT_UPDATED`
- `TIMETREE_EVENT_DELETED`
- `TIMETREE_DRY_RUN`
- `TIMETREE_ERROR`

確認方法:

```bash
docker compose logs -f api
tail -f data/timetree/logs/timetree.log
find data/timetree/artifacts -maxdepth 2 -type f -print
find data/timetree/traces -maxdepth 1 -type f -print
```

失敗時は `artifacts/<timestamp>_<operation>/` に `error.json` と `failure.png` を保存します。`error.json` にはtimestamp、現在URL、操作名、エラー概要、画像パスを含みます。`--debug` をグローバルオプションとしてサブコマンドより前に付けるとHTMLとPlaywright traceも保存します。

```bash
docker compose exec api python -m app.timetree --debug status
```

HTML、trace、スクリーンショットにはカレンダー内容が含まれる可能性があります。外部共有しないでください。

親リポジトリの既存バックアップ処理は `data/` 全体を保存するため、今後のバックアップにはTimeTreeのstorage stateも含まれます。バックアップファイルも認証情報と同じ強さで保護してください。

## 認証失効

`status` が終了コード2と `TIMETREE_AUTH_REQUIRED` を返した場合、再ログインが必要です。Mac側で `login` をやり直し、新しい `storage-state.json` を同じ場所へ安全に転送します。PoCはメールアドレス、パスワード、2FAコードを読み取りません。

## Selector方針と実機調整

操作は次の順で探します。

1. role + accessible name
2. label
3. 安定したinput属性
4. 短いCSS fallback

`nth-child()`、複雑なCSS階層、画面座標は使いません。実DOMでは作成ボタンが `button` / `aria-label="Create an event"`、作成フォームのタイトルが `textarea[name="title"]`、保存がアクセシブル名 `Save`、閉じる操作が `Close`、終日切替が `role="switch"` / `data-test-id="allday-checkbox"` でした。開始日・終了日はそれぞれ `dateTime.startDate` / `dateTime.endDate`、時刻入力は終日を解除した場合に `dateTime.startTime` / `dateTime.endTime` として現れます。詳細欄は `Note` を開いた後の専用textareaです。変更操作では、確認済みのrole・accessible name・安定属性を使い、可視候補が複数なら拒否します。

## ロールバック

DB migration、API route、dashboard変更、新サービスはありません。TimeTree上にactiveなPoCイベントがある場合は、先に各recordを確認して `delete-test --apply` で削除します。その後、この変更で追加した `app/timetree/`、`tests/test_timetree_client.py`、`tests/test_timetree_ownership.py`、`tests/test_timetree_selectors.py`、本ドキュメントを戻し、`.env.example`、`.gitignore`、`.dockerignore`、READMEの追記を戻せばコード上のロールバックは完了です。

認証状態も破棄する場合だけ、サーバー上の `data/timetree/auth/storage-state.json` を削除します。`data/timetree/owned-events.json` は、TimeTree上のPoCイベントが残っていないことを確認するまで削除しないでください。

## この実装で実施した検証

- Python構文検査: 成功
- Ruff静的検査: 成功
- TimeTreeの所有台帳、安全URL、所有トークン、設定originを扱う単体テスト: 8件成功
- `docker compose config --quiet`: 成功
- Playwright 1.46 + Chromium 128で `https://timetreeapp.com` を開く: 成功
- storage stateがない状態を `TIMETREE_AUTH_REQUIRED` / 終了コード2として判定: 成功
- 修正後のheadless smoke testで公開URLが`/intl/ja`へ遷移し、認証情報なしでは`authenticated: false`になることを再確認
- 未認証エラー時の `error.json`、PNG screenshot、debug HTML、Playwright trace保存: 成功
- 変更系selectorが複数の可視要素へ一致した場合の拒否、Calendar List・event detail title・Edit formの遅延描画待機、実際に観測した認証済みURLの永続化、予定詳細URLの厳格な検証、date-only処理、Save事前検証、release announcementの限定的なdismiss、pending台帳のatomic cleanupを含め、PoC単体テストは合計81件成功
- `/signin`と`/intl/ja`の拒否、`/calendars/<id>`の認識、公開ページのfail-closed、複数page、新規tab、storage state/session保存、timeout時に認証ファイルを作らないことを回帰テストで確認
- 認証済みrouteでReact loading終了と操作要素をbounded waitすること、公開routeではapp shellを待たないこと、debug診断に件数だけを含めることを回帰テストで確認
- API全テスト: 35件成功、11件失敗。既存のTimeTree PoC文書に記録済みの同じ11件が失敗しており、今回の変更による新規失敗はありません。既存失敗はインメモリSQLiteの別connectionでtableが見えない問題10件とHEPCO parserの既存期待値差1件です。

実アカウントで認証、対象共有カレンダーの一意な認識、対象カレンダーURLの維持、新規予定フォームを保存せず開けることまで確認済みです。作成・更新・削除の実書き込みは0件です。CRUDは各dry-runとprobe結果を確認するまで`--apply`を付けないでください。
