# Screenshot Crawler

Python + Playwrightで、Webビューアを1ページずつ進めながら本文だけをPNG保存し、正常終了時にZIPへまとめるクローラです。

万能な自動判定は目的にしていません。共通処理を `core/` に置き、サイト差分は `site_adapters/` に閉じ込めます。新しいサイトは Probe → 調査 → Adapter実装 → テスト → 実サイト確認、の順で追加します。

## 現在実装されているもの

- Core Runnerと6状態 (`CONTENT / AD / END / NEXT_CONTENT / LOADING / UNKNOWN`)
- PNG capture、SHA-256 fingerprint、manifest / progress、diagnostics
- Playwright Probe
- BookWalker Adapter
- Manga ONE Adapter
- 既存ChromeへCDP接続するcrawl/loginフロー
- BookWalker canvas / spread capture
- Manga ONE img / spread capture
- manifestをauthorityにしたZIP packagingとlibrary出力
- unit testsとPlaywrightローカルfixture integration tests

## 最初に読むもの

1. `docs/SPEC.md` — 現在の製品仕様・受け入れ条件
2. `docs/ARCHITECTURE.md` — 責務分離と依存方向
3. `docs/DECISIONS.md` — 重要な設計判断
4. `docs/CODEX_IMPLEMENTATION_GUIDE.md` — 既存実装を変更するときのルール
5. `docs/SITE_ADAPTER_GUIDE.md` — 新規サイト対応の作り方
6. `docs/TEST_STRATEGY.md` — テスト方針

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
playwright install chromium
```

Windows PowerShellを主な実行環境として想定しています。

## 基本ワークフロー

```text
URLを人手または別プログラムから取得
        ↓
必要ならprobeで対象サイトを観察
        ↓
既存Adapterまたは新規Adapterを使用
        ↓
少数ページ・最終ページ付近を確認
        ↓
本実行
        ↓
END / NEXT_CONTENTで正常終了したらZIP化
```

Crawler本体はURL一覧の収集を担当しません。

## CDPで既存Chromeへ接続

BookWalkerやManga ONEのcrawl/loginは、通常のChromeセッションを維持するため、専用profileで起動したChromeへCDP接続します。

BookWalker:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_bookwalker_chrome.ps1
```

Manga ONE:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_mangaone_chrome.ps1
```

必要なら `.env` のサイト別 `*_CDP_ENDPOINT` で接続先を変更できます。

例:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --url "https://bookwalker.jp/de6de7534d-7022-481d-b2d3-05f03f384454/" `
  --output-dir output\crawl-bookwalker
```

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site mangaone `
  --url "https://manga-one.com/manga/2379/chapter/214131" `
  --output-dir output\crawl-mangaone
```

## Outputの安全ルール

新規crawlの `--output-dir` は、存在しないdirectoryまたは空directoryである必要があります。既存runの暗黙resumeは行いません。

実行中は概ね次の形になります。

```text
output/crawl-xxx/
├─ page-0001.png
├─ page-0002.png
├─ manifest.json
├─ progress.json
└─ diagnostics/   # 失敗時に作られる場合あり
```

正常な `END` / `NEXT_CONTENT` 後は、manifestに記載されたPNGだけをZIPへ格納します。manifestにない古いPNGは混入しません。中間crawl directoryは、manifest / progress / manifest記載PNG以外のファイルを含まない場合だけ削除されます。

失敗runは調査用に残します。

## Resume

自動resumeは現在未実装です。既存の非空run directoryを新規runとして上書きせず、明示的に拒否します。`progress.json` は実行状況の記録であり、現時点では自動resume機能を意味しません。

## サイト固有の挙動

実サイトで確認済みの判定ロジックを、一般論だけを理由に変更しないでください。特にBookWalkerとManga ONEの終了判定・ページ送り・capture方式は各Adapter READMEをauthorityとして確認してください。
