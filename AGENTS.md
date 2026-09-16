# AGENTS.md

このリポジトリでは、Codexは以下をauthorityとして実装する。

## Authority order

1. `docs/SPEC.md`
2. `docs/ARCHITECTURE.md`
3. `docs/DECISIONS.md`
4. `docs/CODEX_IMPLEMENTATION_GUIDE.md`
5. 現在のコードとテスト
6. Site Adapter固有README / probe出力

仕様と実装が競合した場合、黙って仕様を変更しない。差分を明示し、最小修正で仕様へ合わせる。

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

## Before coding

対象フェーズについて、まず `docs/CODEX_IMPLEMENTATION_GUIDE.md` の目的・変更範囲・受け入れ条件を確認する。

## After coding

最低限以下を実行する。

```bash
pytest -q
```

可能なら以下も実行する。

```bash
ruff check src tests
```

最後に以下を報告する。

- 変更したファイル
- 仕様上の判断
- テスト結果
- 未解決事項・実サイト確認が必要な事項
