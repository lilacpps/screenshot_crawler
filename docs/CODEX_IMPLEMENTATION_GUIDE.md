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
7. 対応する `note/`

`note/` は詳細な現行実装スナップショットだが、上位authorityではない。上位authority / code / testsと食い違う場合はnoteを修正する。

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
- **実装・仕様変更と同じ変更で対応する `note/` を必ず同期する**

## 3. Note同期

変更対象ごとの更新先:

- Core / Runner / output / packaging / browser / diagnostics / resume → `note/00_core.md`
- BookWalker → `note/01_bookwalker.md`
- Manga ONE → `note/02_mangaone.md`
- 新規site → 対応するsite noteを追加

共通変更が特定siteの実挙動に影響する場合、Core noteとsite noteの両方を更新する。

noteは履歴ログではなく**現行仕様の詳細説明**として保つ。古い仕様を残したまま末尾へ新情報だけ追記しない。現在の挙動、主要signal、CLI/設定、出力、安全装置、既知の制約、live verificationを読み直して本文を更新する。

秘密情報は書かない。詳細は `note/README.md`。

## 4. Core bug fix時

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

Coreの挙動を変えたら `note/00_core.md` を更新する。

## 5. Site Adapter bug fix時

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

Site Adapterの挙動を変えたら対応site noteを更新する。

## 6. Output / packaging変更時

必須:

- 新規runは非空output directoryを拒否
- 既存runを暗黙上書きしない
- ZIP対象はmanifest `pages[].file`
- manifest外PNGを混入させない
- manifest記載ファイル欠落はfail
- user fileを含むdirectoryを丸ごと削除しない

Resumeは現在未実装。resume機能を追加する場合は明示CLIと受け入れ条件を先に定義する。

変更後は `note/00_core.md` のoutput / packaging / resume説明を同期する。

## 7. 新規Site Adapter追加時

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
- `note/<nn>_<site>.md`
- 必要なら明示的に利用される設定ファイル
- unit / local integration tests

`config.yaml` は必須ではない。Pythonと二重authorityになる未使用configは追加しない。

## 8. Test

```bash
pytest -q
ruff check src tests
```

Playwright integrationがskipされた場合は、その件数と理由を最終報告に書く。

実サイトでしか確認できない事項は「未確認」と明示する。

## 9. 完了条件 / 報告

完了前に確認する。

- 実装とdocsが一致している
- 変更に対応するtestsがある
- 対応する `note/` が現行実装へ同期されている
- note更新不要なら理由が明確

最終報告には最低限:

- 変更ファイル
- 更新したnote
- 変更した挙動
- 既存挙動をどう保護したか
- 追加/更新テスト
- pytest / ruff結果
- skipped test
- 実サイト確認の有無
- 残課題
