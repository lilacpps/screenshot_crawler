# Screenshot Crawler Starter

Python + Playwright で、Webビューアを1ページずつ進めながら本文ページだけをPNG保存するための実装スターターです。

このリポジトリは「どんなサイトでも自動対応する万能クローラ」を目的にしません。共通処理を `core/` に置き、サイト差分は `site_adapters/` に閉じ込め、新規サイトは Probe → 調査 → Adapter実装 → テスト、の流れで追加します。

## 最初に読むもの

1. `docs/SPEC.md` — 製品仕様・受け入れ条件
2. `docs/ARCHITECTURE.md` — 責務分離と依存方向
3. `docs/CODEX_IMPLEMENTATION_GUIDE.md` — Codexに実装を依頼する順序と制約
4. `docs/SITE_ADAPTER_GUIDE.md` — 新規サイト対応の作り方
5. `docs/TEST_STRATEGY.md` — テスト方針
6. `docs/DECISIONS.md` — 重要な設計判断

## 想定ワークフロー

```text
URLを人手または別プログラムから取得
        ↓
probeで対象サイトを観察
        ↓
既存pattern / adapterを確認
        ↓
Codexが site adapter を実装
        ↓
少数ページ・広告前後・最終ページを確認
        ↓
本実行
```

## ディレクトリ

```text
screenshot_crawler_starter/
├─ docs/                       仕様・設計・Codex向け実装指示
├─ src/screenshot_crawler/
│  ├─ core/                    共通エンジン
│  ├─ site_adapters/           サイト固有実装
│  ├─ patterns/                再利用できる表示方式の補助部品
│  └─ probe/                   新規サイト調査
├─ tests/
│  ├─ unit/
│  ├─ integration/
│  └─ fixtures/
├─ examples/
├─ scripts/
├─ pyproject.toml
└─ .gitignore
```

## セットアップ（実装後の想定）

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .[dev]
playwright install chromium
```

Windows PowerShell を主な実行環境として想定しています。

## 現在の状態

このスターターには、型・インターフェース・例示用Adapterなどの骨格だけを入れています。Coreの本実装は `docs/CODEX_IMPLEMENTATION_GUIDE.md` のフェーズ順でCodexに依頼する想定です。
# Screenshot Crawler

## Existing Chrome profile via CDP

For sites whose authentication or viewer behavior depends on the regular
browser profile, start a dedicated Chrome profile manually, sign in normally,
and attach the crawler over Chrome DevTools Protocol. This mode does not read
or create `.auth/*.json`.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_bookwalker_chrome.ps1
```

Log in manually in that Chrome window, then run:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli crawl `
  --site bookwalker `
  --cdp-endpoint http://127.0.0.1:9222 `
  --url "https://bookwalker.jp/de6de7534d-7022-481d-b2d3-05f03f384454/" `
  --output-dir output\crawl-bookwalker-cdp `
  --max-pages 5 `
  --keep-open
```

The crawler creates a new tab in the existing Chrome context, follows the
product-page read link, and leaves the Chrome process open when it finishes.
