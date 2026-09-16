# Codex Implementation Guide

このrepositoryはCore・Probe・BookWalker・Manga ONEまで実装済み。Codexは既存動作を保ちながら変更する。

## 1. Authority

作業前に最低限読む。

1. `AGENTS.md`
2. `docs/SPEC.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`
5. 対象Site Adapter README
6. 対象コードとテスト
7. 対応する `note/`

`note/` は詳細な現行実装スナップショットだが、上位authorityではない。上位authority / code / testsと食い違う場合はnoteを修正する。

現行仕様とコードが競合して見える場合、勝手に大規模変更せず差分を報告する。

**BookWalker / Manga ONEで実サイト確認済みのviewer/capture/END挙動を、一般論だけを理由に変更しない。**

## 2. 共通ルール

- Coreにsite-specific selector / URL branchを入れない
- 不要な抽象化を追加しない
- 独自DSLを作らない
- Patternのための深い継承を作らない
- UNKNOWNを無理に突破しない
- retry / waitはbounded
- データ破壊より停止を優先
- 実装変更には対応テストを追加・更新
- 外部サイト依存CIを作らない
- 実サイト著作物をfixtureへ保存しない
- 実装・仕様変更と同じ変更で対応する `note/` を同期する

## 3. Browser Session policy

採用済みの目標仕様:

```text
shared Crawler Chrome/profile
    ↑ CDP
Playwright Browser/Context/Page
    ↓
Core Runner
    ↓
Site Adapter
```

原則:

- Real-site browserへの接続はCDP
- 通常のsite操作はPlaywright
- 標準profileは `.chrome-crawler/`
- 標準global endpointは `CRAWLER_CDP_ENDPOINT`
- Site AdapterはChrome launch / profile / endpoint / `connect_over_cdp()` を扱わない
- Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う

endpoint優先順位:

1. `--cdp-endpoint`
2. `<SITE>_CDP_ENDPOINT`
3. `CRAWLER_CDP_ENDPOINT`
4. `http://127.0.0.1:9222`

site-specific endpoint/profileは例外overrideでありdefaultではない。

## 4. Browser Session移行時

共通launcher/profileへのPhase 2移行を実装済み。移行ではbrowser/session層だけを変更し、BookWalker/Manga ONEのviewer logicを原則変更しない。

目標成果物:

- 共通 `start_crawler_chrome.ps1`
- `.chrome-crawler/`
- global `CRAWLER_CDP_ENDPOINT`
- site-specific endpoint overrideのfallback
- 既存site launcherはlegacy / compatibility pathとして残し、Phase 3で削除を判断

禁止:

- Adapter内でChromeをlaunchする
- Adapter内でCDP endpointを解決する
- Adapter内で `connect_over_cdp()` する
- Raw CDPを通常DOM操作の代わりに大量利用する

## 5. Authentication変更時

login sessionのauthorityはChrome profile。

- credentials inputは `.env` 等でよい
- login DOM操作はsite handler + Playwrightの専用new Page
- Cookie / localStorage / IndexedDB等のsession保存はChromeへ任せる
- site別storage-state JSONを標準経路として増やさない
- CAPTCHA / MFA / validation errorを自動突破しない

## 6. Note同期

変更対象ごとの更新先:

- Core / Runner / output / packaging / browser / diagnostics / resume → `note/00_core.md`
- BookWalker → `note/01_bookwalker.md`
- Manga ONE → `note/02_mangaone.md`
- 新規site → 対応site noteを追加

共通変更が特定siteの実挙動に影響する場合、Core noteとsite noteの両方を更新する。

noteは履歴ログではなく現行実装の詳細説明として保つ。古い仕様を末尾追記だけで残さない。

## 7. Core bug fix時

最初に問題がSite Adapter固有かCore共通かを分離する。

Core変更では特に確認する。

- END / NEXT_CONTENTをcaptureしない
- `max_pages`到達後でもterminal stateを正常終了できる
- fingerprint duplicate guard
- same-content guard
- multiple capture targets
- context change
- output directory安全性
- manifest基準packaging

現行Runnerではcapture fingerprintが保存dedupeのauthority。identity優先方式へ変更する場合は実viewer遷移を先に確認する。

## 8. Site Adapter bug fix時

変更前にsite READMEとsite noteのlive observationsを読む。

調査すること:

1. capture target
2. page identity
3. content context
4. next操作
5. page change wait
6. loading
7. final content
8. final advance後の挙動
9. NEXT_CONTENT

### Manga ONE

現在のENDは「final advance後、page imagesが `end_grace_ms` 継続して消失する」既知挙動を利用する。実DOM未確認のgeneric END selectorへ置換しない。

### BookWalker

page counter / `#endOfBook` / `#eobNext` / known final-navigation behaviorを組み合わせている。単一signalへ単純化しない。

## 9. Output / packaging変更時

必須:

- 新規runは非空output directoryを拒否
- 既存runを暗黙上書きしない
- ZIP対象はmanifest `pages[].file`
- manifest外PNGを混入させない
- manifest記載ファイル欠落はfail
- user fileを含むdirectoryを丸ごと削除しない

Resumeは現在未実装。追加する場合は明示CLIと受け入れ条件を先に定義する。

## 10. 新規Site Adapter追加時

最初にProbeまたは手動観測で本文描画、capture、next、change detection、identity、context、広告、終端、NEXT_CONTENT、loadingを確認する。

成果物の目安:

- `site_adapters/<site>/adapter.py`
- `site_adapters/<site>/README.md`
- `note/<nn>_<site>.md`
- 必要ならlogin handler
- 必要なら明示的に利用される設定ファイル
- unit / local integration tests

Browser Sessionは既存共通層を使い、新規siteのために専用launcher/profileを最初から作らない。必要性が実確認できた場合だけoverrideを追加する。

## 11. Test

```bash
pytest -q
ruff check src tests
```

Browser Session共通化では最低限:

- global endpoint resolution
- site-specific endpoint override
- remote Chromeを閉じない
- Adapterがbrowser/session管理へ依存しない
- login/crawlが同じBrowser Session modelを使う

を確認する。

Phase 2では `scripts/start_crawler_chrome.ps1` と `.chrome-crawler/` を標準運用にし、loginは既存タブを再利用せず専用new Pageを閉じる。旧site launcher/profileはrollback用に残す。

Playwright integrationがskipされた場合は件数と理由を報告する。

## 12. 完了条件 / 報告

完了前に確認する。

- 実装とdocsが一致
- 対応testsあり
- 対応note同期済み
- 実サイト確認済み/未確認を区別

最終報告には最低限:

- 変更ファイル
- 更新したnote
- 変更した挙動
- 既存挙動をどう保護したか
- pytest / ruff結果
- skipped test
- 実サイト確認の有無
- 残課題
