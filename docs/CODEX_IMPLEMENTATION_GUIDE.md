# Codex Implementation Guide

このrepositoryはCore・Probe・BookWalker・Manga ONEまで実装済み。Codexは「Phase 1から新規実装する」のではなく、既存動作を保ちながら変更する。

## 1. Authority

作業前に最低限読む。

1. `AGENTS.md`
2. `docs/SPEC.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DECISIONS.md`
5. 対象Site Adapter README
6. 対象コードとテスト

現行仕様とコードが競合して見える場合、勝手に大規模変更せず差分を報告する。

**BookWalker / Manga ONEで実サイト確認済みの挙動を、一般論だけを理由に変更しない。**

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

## 3. Core bug fix時

最初に、問題がSite Adapter固有かCore共通かを分離する。

Core変更では特に確認する。

- END / NEXT_CONTENTをcaptureしない
- `max_pages`到達後でもterminal stateを正常終了できる
- fingerprint duplicate guard
- same-content guard
- multiple capture targets
- context change
- output directory安全性
- manifest基準packaging

現行Runnerではcapture fingerprintが保存dedupeのauthority。identity優先方式へ変更する場合は、BookWalker/Manga ONEの実viewer遷移を先に確認する。

## 4. Site Adapter bug fix時

変更前にsite READMEのlive observationsを読む。

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

## 5. Output / packaging変更時

必須:

- 新規runは非空output directoryを拒否
- 既存runを暗黙上書きしない
- ZIP対象はmanifest `pages[].file`
- manifest外PNGを混入させない
- manifest記載ファイル欠落はfail
- user fileを含むdirectoryを丸ごと削除しない

Resumeは現在未実装。resume機能を追加する場合は明示CLIと受け入れ条件を先に定義する。

## 6. 新規Site Adapter追加時

最初にProbeまたは手動観測で以下を確認する。

- 本文描画方式
- capture target
- next操作
- page change検知
- identity
- content context
- 広告
- 最終ページ後
- NEXT_CONTENT
- loading完了

成果物の目安:

- `site_adapters/<site>/adapter.py`
- `site_adapters/<site>/README.md`
- 必要なら明示的に利用される設定ファイル
- unit / local integration tests

`config.yaml` は必須ではない。Pythonと二重authorityになる未使用configは追加しない。

## 7. Test

```bash
pytest -q
ruff check src tests
```

Playwright integrationがskipされた場合は、その件数と理由を最終報告に書く。

実サイトでしか確認できない事項は「未確認」と明示する。

## 8. 完了報告

最低限:

- 変更ファイル
- 変更した挙動
- 既存挙動をどう保護したか
- 追加/更新テスト
- pytest / ruff結果
- skipped test
- 実サイト確認の有無
- 残課題
