# Test Strategy

## 1. 目的

Core回帰とSite Adapter前提崩壊を分けて検出する。実サイト確認済みの挙動を、根拠なく一般化したロジックで置換しない。

## 2. Unit Tests

実browser不要のものを対象にする。

- PageState / models
- fingerprint
- Runner guards
- max_pages境界
- duplicate / same-content
- manifest / progress
- output directory safety
- packaging / manifest validation
- Adapter helper / parser / naming

## 3. Integration Tests

`tests/integration/test_local_viewer_flows.py` でPlaywright + 人工ローカルviewerを使う。

主な対象:

- CONTENT → CONTENT → END
- AD skip
- NEXT_CONTENT
- LOADING → CONTENT
- unresolved LOADING timeout
- UNKNOWN stop
- same-content guard
- spread capture
- max_pages境界
- Manga ONEのimage-disappearance END heuristic
- Manga ONE chapter change

外部サイトへ常時依存するCIテストは置かない。

Integration testsはChromiumが利用できない環境ではskipされる。そのためテスト結果を確認するときは、単にpytest exit codeだけでなくpassed / skipped件数も確認する。

## 4. Packaging tests

最低限:

- manifest記載PNGだけZIPへ入る
- manifest外の古いPNGはZIPへ入らない
- manifest記載PNG欠落は失敗
- 無関係ファイルがあるsource directoryをrmtreeしない

## 5. 実サイト確認

Adapterの挙動を変更する場合は、可能な範囲で対象サイトを確認する。

最低観点:

1. 開始直後
2. 通常数ページ
3. spread / single transition
4. 広告前後（存在する場合）
5. 最終本文
6. 最終本文後
7. NEXT_CONTENT
8. 読み込みが遅いケース

実サイトの著作物・DOM snapshotを恒久fixtureへコピーしない。

## 6. Regression priority

優先度が高い失敗:

- 最終本文を保存せず終了
- viewer終端を認識できずtimeout
- 広告やnext contentを本文として保存
- 同一ページを大量保存
- 古いrun PNGを新ZIPへ混入
- user fileをcleanupで削除
- UNKNOWNなのに進行
- Coreへのsite-specific分岐混入

## 7. 実行

```bash
pytest -q
ruff check src tests
```

実サイトAdapterの変更がないdocs-only変更では、コードテストの再実行は必須ではない。ただしdocsが記述する挙動は現在コードと既存テストに照らして確認する。
