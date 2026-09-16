# Codex Implementation Guide

このファイルはCodexに実装を依頼するときのauthorityです。

## 0. 共通ルール

Codexは実装前に次を読むこと。

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. 対象フェーズの受け入れ条件

守ること:

- Coreにサイト固有コードを入れない
- 不要な抽象化を追加しない
- 独自DSLを作らない
- Patternのための深い継承を作らない
- UNKNOWNを無理に突破しない
- 実装と同時にテストを追加する
- 既存仕様とコードが競合したら、仕様を勝手に変更せず差分を報告する

## Phase 1: Contracts / Models

### 目的

CoreとSite Adapterの境界を固定する。

### 変更範囲

- `core/models.py`
- `core/state.py`
- `core/errors.py`
- `site_adapters/base.py`
- unit tests

### 必須事項

- `PageState`
- `ContentIdentity`
- `ContentContext`
- `CapturedPage`
- `RunConfig`
- Adapter ABC

### 受け入れ条件

- 型が循環importしない
- Adapter契約がSPECを満たす
- unit testが通る

## Phase 2: Browser / Capture / Fingerprint

### 目的

ページループ以外の共通I/Oを実装する。

### 変更範囲

- `core/browser.py`
- `core/capture.py`
- `core/fingerprint.py`
- tests

### 必須事項

- Chromium起動・Context管理
- locator screenshot bytes取得/保存
- SHA-256
- viewport設定

### 非対象

- Runnerの状態遷移
- Site Adapter実装

## Phase 3: Progress / Manifest / Diagnostics

### 目的

途中状態と異常時情報を確実に残す。

### 変更範囲

- `core/progress.py`
- `core/diagnostics.py`
- tests

### 受け入れ条件

- JSONがatomicに近い形で更新されること（temporary file → replaceを推奨）
- 既存manifestを壊しにくい
- diagnostics失敗が元例外を隠さない

## Phase 4: Runner

### 目的

状態機械を実装する。

### 変更範囲

- `core/runner.py`
- unit/integration tests

### 状態遷移

- CONTENT: capture対象
- AD: skipして次へ
- LOADING: bounded retry
- END / NEXT_CONTENT: 正常終了
- UNKNOWN: diagnostics保存して異常終了

### 受け入れ条件

- max_pages
- same-content guard
- retry上限
- Adapter例外の扱い
- 正常終了と異常終了を区別

## Phase 5: Probe

### 目的

新規サイト対応の材料収集。

### 変更範囲

- `probe/collector.py`
- `probe/models.py`
- CLI

### 収集候補

- screenshot
- HTML
- URL/title
- visible img metadata
- canvas metadata
- button候補
- computed background-image候補

### 非対象

- 正しい次ボタンの完全自動特定
- AI分類

## Phase 6: Example Adapter

### 目的

Adapter実装の見本を1つ用意する。

`site_adapters/example/` は実サイトではなくfixtureベースでよい。

### 受け入れ条件

- Coreを変更せずAdapter追加だけで動くことを示す
- READMEに判定方式を記録

## 新規サイト対応時のCodex指示テンプレート

```text
対象サイトのSite Adapterを実装してください。

最初に以下をauthorityとして読んでください。
- docs/SPEC.md
- docs/ARCHITECTURE.md
- docs/SITE_ADAPTER_GUIDE.md
- 既存patterns/
- 既存site_adapters/
- 対象probe出力

目的:
指定URLの現在コンテンツについて、本文だけを順番にPNG保存し、広告を保存せず、次話へ移る前に停止する。

必ず調査すること:
1. 本文描画方式
2. capture target
3. next操作
4. page change検知
5. page number / page id
6. episode/chapter/content id
7. 広告判定
8. 最終ページ後の挙動
9. 次話遷移の検知
10. loading完了判定

制約:
- Coreへのサイト固有if追加は禁止
- 既存Patternが使えるなら再利用
- 1サイト固有ならPattern追加しない
- UNKNOWNでは停止

成果物:
- site_adapters/<site>/adapter.py
- site_adapters/<site>/config.yaml
- site_adapters/<site>/README.md
- 必要なテスト

確認:
- 通常ページ
- 広告前後
- 最終ページ
- 最終ページ後
- 次話遷移
- ページ変更失敗
```
