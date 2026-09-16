# AGENTS.md

このリポジトリでは、Codexは以下をauthorityとして実装する。

## Authority order

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
5. 現在のコードとテスト
6. Site Adapter固有README / probe出力
7. `note/` の現行実装ノート

`note/` は詳細な現行実装スナップショットとして常に更新する。ただし、上位authorityと競合する場合は上位authorityを優先し、note側を修正する。

仕様と実装が競合した場合、黙って仕様を変更しない。差分を明示し、既存の実サイト確認済み挙動を壊さない最小修正を選ぶ。

## Browser Session policy

Real-site automationの標準設計は次とする。

```text
shared Crawler Chrome/profile
    ↑ CDP
Playwright Browser / Context / Page
    ↓
Core Runner
    ↓
Site Adapter
```

必須ルール:

- Real-site browserへの接続は原則CDP
- 接続後の通常操作はPlaywright `Page` / `Locator`
- 共通profile `.chrome-crawler/` をdefaultとする
- global endpoint `CRAWLER_CDP_ENDPOINT` をdefaultとする
- site-specific endpoint/profileは必要な場合だけoverride
- Site AdapterからChrome launch / profile選択 / endpoint解決 / `connect_over_cdp()` を行わない
- Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う

共通launcher/profileを標準化した後も、shared profileでBookWalker/Manga ONEのlive verificationが完了するまでは既存site別launcher/profileをrollback用に残してよい。ただし最終設計として拡張せず、live verification完了後に削除を判断する。

## Implementation rules

- Python 3.12+ / Playwright Pythonを使用する。
- Coreにサイト固有selector、URL、サイト名による分岐を追加しない。
- サイト固有挙動は `site_adapters/<site>/` に置く。
- YAMLで複雑な条件分岐を表現する独自DSLを作らない。
- Patternは軽量な再利用部品に留め、深い継承階層を作らない。
- 1サイトだけで必要な処理を早期に共通化しない。
- UNKNOWN状態では無理に進行させない。
- retryには必ず上限を設ける。
- max_pages / same-content guardを外さない。
- 実装変更には対応するテストを追加・更新する。
- 外部実サイトへの恒常的なCI依存は作らない。
- fixtureには実サイトの著作物をそのまま保存しない。

## Note synchronization rule

仕様・実装・テスト・運用方法を変更した場合、**同じ変更の中で対応する `note/` も更新することを必須**とする。

更新先:

- Core / Runner / output / packaging / browser / diagnostics / resume等の共通変更 → `note/00_core.md`
- BookWalker固有変更 → `note/01_bookwalker.md`
- Manga ONE固有変更 → `note/02_mangaone.md`
- 新規サイト追加 → 対応する `note/<nn>_<site>.md` を追加
- 共通変更が実サイト挙動にも影響する場合 → `00_core.md` と影響するsite noteの両方

noteには少なくとも、現在の挙動、主要な判定ロジック、設定/CLI、出力、既知の制約、実サイト確認状況を残す。

履歴だけを追記して古い仕様を残すのではなく、読めば現行仕様が分かる状態へ本文を更新する。古い判断を残す必要がある場合は `docs/DECISIONS.md` またはGit履歴を使う。

認証情報、Cookie、storage state、秘密情報はnoteへ書かない。

詳細は `note/README.md` を参照する。

## Before coding

1. `docs/CODEX_IMPLEMENTATION_GUIDE.md` を読む。
2. 変更対象に対応する `note/` を読む。
3. noteとコードが食い違う場合はcode/testsと上位authorityを確認し、作業内でnoteも同期する。
4. Browser関連変更では `docs/SPEC.md` のBrowser Session Modelを確認する。

## After coding

最低限以下を実行する。

```bash
pytest -q
```

可能なら以下も実行する。

```bash
ruff check src tests
```

完了前に、変更内容に対応する `note/` が更新されていることを確認する。note更新が不要な変更なら、その理由を最終報告に書く。

最後に以下を報告する。

- 変更したファイル
- 更新したnote
- 仕様上の判断
- テスト結果
- 未解決事項・実サイト確認が必要な事項
