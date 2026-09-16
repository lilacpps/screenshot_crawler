# Design Decisions

## D-001 Pythonを採用

### 決定
Python 3.12+ + Playwright Pythonを使用する。

### 理由
必要なPlaywright機能を満たし、利用者の習熟度を優先する。

---

## D-002 万能自動判定をv1で目指さない

### 決定
新規サイトはprobeしてSite Adapterを追加する。

### 理由
終了挙動・広告・次コンテンツ遷移がサイトごとに異なり、完全自動化は誤取得リスクが高い。

---

## D-003 CoreとSite Adapterを分離

### 決定
サイト固有ルールをCoreに入れない。

### 理由
サイト追加・修正ごとの回帰を抑える。

---

## D-004 設定ファイルだけで全挙動を表現しない

### 決定
設定ファイルは必要な単純データに限定し、複雑なロジックはPython Adapterに置く。未使用configをauthority扱いしない。

### 理由
独自DSL化と二重authorityを避ける。

---

## D-005 UNKNOWNでは停止

### 決定
不明状態で自動継続しない。

### 理由
別コンテンツ・広告・意図しない画面を大量保存するリスクを抑える。

---

## D-006 Locator / content bufferを優先

### 決定
固定screen cropより本文Locatorを優先する。Canvasでraw PNGを取得できる場合はcontent bufferを利用する。

### 理由
viewer UI混入と画面環境依存を減らす。

---

## D-007 Patternは補助部品

### 決定
Patternを重い継承frameworkにしない。

### 理由
例外が多い領域で抽象化を先行させない。

---

## D-008 Real-site automationはCDP接続を標準とする

### 決定
Real-siteの `crawl` / `login` は、外部で起動した通常ChromeへPlaywright `connect_over_cdp()` で接続する方式を標準とする。

Crawlerが実サイトごとにChromiumをlaunchして認証状態を個別管理する方式は標準にしない。

### 理由
通常Chromeのlogin/session、Cookie、localStorage等を維持しやすく、viewer固有の通常browser挙動を保ちやすい。またCrawler終了時にChrome process自体を終了せず、Crawlerが利用したPageだけを閉じられる。

---

## D-009 Resumeはv1.1では未実装

### 決定
既存の非空run directoryは拒否し、暗黙resumeやmanifest/progress上書きを行わない。

### 理由
不完全なresumeより既存成果物保護を優先する。

---

## D-010 保存dedupeはcapture fingerprintをauthorityとする

### 決定
現行RunnerではSHA-256 capture fingerprintを保存重複判定に使う。ContentIdentityはchange detectionと記録に利用する。

### 理由
実サイトで動作していたBookWalker/Manga ONEの遷移挙動を維持する。identity優先へ変更する場合は実viewerの連続spread等を先に確認する。

---

## D-011 Manifestをpackaging authorityとする

### 決定
ZIP対象はdirectory globではなくmanifest `pages[].file` とする。新規runは非空directoryを拒否し、無関係ファイルを含むsource directoryは丸ごとcleanupしない。

### 理由
古いPNG混入とuser file削除を防ぐ。

---

## D-012 Site固有の終端ヒューリスティックを許容する

### 決定
END判定に全サイト共通の「明示END DOM必須」ルールを置かない。実観測が安定している場合はboundedなsite-specific heuristicをAdapterに置く。

### 理由
Manga ONEでは最終advance後のpage image消失が実動作上の終端signalであり、未確認generic selectorへの置換の方が回帰リスクが高い。

---

## D-013 `note/` を現行実装スナップショットとして同期する

### 決定
仕様・実装・テスト・運用方法を変更した場合、同じ変更の中で対応する `note/` を更新する。

- Core共通変更は `note/00_core.md`
- Site固有変更は対応するsite note
- 共通変更がsite挙動へ影響する場合は両方

noteは履歴ログではなく「現在どう動くか」を詳しく説明する場所とする。履歴はGitと `docs/DECISIONS.md` に残す。

noteはauthority orderではcode/testsより下に置き、上位authorityと競合した場合はnoteを修正する。

### 理由
実装詳細をチャットや過去コミットだけに依存せず、次回作業時に現在の前提・既知の実サイト挙動・運用方法を素早く復元できるようにするため。

---

## D-014 共通Crawler Chrome / profileを標準とする

### 決定
Real-site automationでは、原則として1つの専用Crawler Chromeと1つの共通profileを利用する。

目標profile:

```text
.chrome-crawler/
```

BookWalker、Manga ONE、将来追加するサイトの認証状態は、Chrome自身がこのprofile内のCookie / localStorage / IndexedDB等としてサイトごとに保持する。

Crawler側では `bookwalker-auth.json` のようなsite別storage-state fileを標準の認証authorityにしない。

### 理由
普通のChromeで複数サイトへログインするのと同じモデルに寄せることで、認証状態管理をCrawlerから切り離し、site追加時のbrowser/session実装を減らすため。

---

## D-015 接続はCDP、操作はPlaywrightを標準とする

### 決定
CDPはBrowser Sessionへの接続手段として使い、通常のサイト操作はPlaywrightの高水準APIで行う。

標準:

- `connect_over_cdp()`
- `Page`
- `Locator`
- `goto()`
- `click()`
- `wait_for_*()`
- `evaluate()`
- `screenshot()` / canvas capture

Raw CDP Protocol (`new_cdp_session()` / `session.send()` 等) は、Playwright APIでは実現困難なChrome固有機能が必要な場合だけ使う。

### 理由
Locator、auto-wait、frame/popup処理、timeout、screenshot等をPlaywrightへ任せた方が実装が単純で安定する。CDPを低レベル操作APIとして各Adapterへ広げると保守性が下がる。

---

## D-016 Site AdapterはBrowser接続方式を知らない

### 決定
Site AdapterはPlaywright `Page` / `Locator` を受け取り、サイト固有DOMとviewer挙動だけを扱う。

Adapterから以下を行わない。

- Chrome process launch
- profile directory選択
- CDP endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle管理

これらはCLI / Browser Session Layerの責務とする。

### 理由
Browser session管理とsite-specific automationを分離し、新規site追加をAdapter実装だけに近づけるため。

---

## D-017 共通CDP endpointをdefaultとしsite-specific overrideを許可する

### 決定
目標のendpoint解決順は次とする。

1. 明示CLI `--cdp-endpoint`
2. site-specific `<SITE>_CDP_ENDPOINT`
3. global `CRAWLER_CDP_ENDPOINT`
4. default `http://127.0.0.1:9222`

通常はglobal endpointと共通Crawler Chromeを使う。siteごとに別profile / Chrome instanceが必要になった場合だけsite-specific endpointでoverrideする。

### 理由
通常運用を単純化しつつ、複数account、extension差、site固有設定、session分離などの例外を将来許容するため。

---

## D-018 Browser Session共通化は仕様先行で移行する

### 決定
まずdocsを上記モデルへ更新し、その後に実装を移行する。

移行完了までは既存の `start_bookwalker_chrome.ps1` / `start_mangaone_chrome.ps1` とsite-specific profileがコード上に残っていてよい。ただしそれらを最終設計とは扱わない。

### 理由
BookWalker/Manga ONEの実サイトで動作しているAdapter挙動を壊さず、browser/session層だけを段階的に差し替えるため。

---

## D-019 共通Crawler Chrome launcherを標準運用にする

### 決定
Phase 2以降のreal-site運用では、`scripts/start_crawler_chrome.ps1` がrepository root基準で `.chrome-crawler/` をprofileに使い、port `9222` でChromeを起動する。既存listenerがある場合は二重起動せず、既存Chromeを利用する。

BookWalker/Manga ONEのloginは共通Chromeの専用new Pageで実行し、login後はPageだけ閉じる。認証sessionはshared profileへ保存し、remote Chrome processは閉じない。

旧site-specific launcher/profileはrollback用legacy / compatibility pathとして残し、削除はPhase 3で判断する。

### 理由
siteごとのprofile競合を避け、BookWalkerとManga ONEのsessionを同じChromeで保持できるようにする。既存viewer behaviorを変更せず、運用入口だけを共通化するため。
