# Site-native Bounded Discovery

Status: **ADOPTED SPECIFICATION / NOT YET IMPLEMENTED**

この文書は `docs/DISCOVERY_AND_BATCH.md` のDiscovery仕様を補足する詳細仕様である。

## 1. 目的

複数siteで同一または重複する内容が配信される場合でも、cross-siteの話数名寄せやItem統合に依存せず、利用者がsiteごとに明示したlisting範囲だけをDiscovery対象にできるようにする。

採用方針:

- 範囲は各site自身のcontent identityとlisting orderで決める
- 範囲内で観測したrecordはすべて通常どおりCatalogへ同期する
- 別siteとの内容重複は許容する
- cross-site identity resolutionをDiscoveryの正しさの前提にしない
- 誤った名寄せによって未取得contentをcompleted扱いするリスクを避ける
- Catalog schema、Batch Planner / Executor、CrawlerRunnerの契約は変更しない

優先するfailure modeは `false negative / no dedupe -> duplicate crawl` であり、これは許容する。`false positive cross-site match -> 未取得contentをcompleted扱い` は許容しない。

## 2. 非目標

初期実装では以下を行わない。

- title / order_label / order_keyからのcross-site話数名寄せ
- 全角数字・漢数字・前後編等を使ったcross-site equivalence判定
- cross-site Itemのautomatic merge / reparent
- 1:1 / 1:Nの自動対応付け
- 別siteのItemへのcompleted伝播
- scopeに基づくCatalog row削除
- Catalog schema migration
- bounded fullにおけるscope内missing-source reconciliation

既存のcross-site duplicate warningはwarning onlyのまま維持してよい。warningをmerge、delete、reparent、completed化の根拠にしてはならない。

## 3. Watchlist schema

Watchlist targetにoptionalな `discovery_scope` を追加する。

```yaml
targets:
  - key: example-site-a
    work_key: example-work
    site: site-a
    url: https://example.invalid/series/123/episode/999
    enabled: true
    label: 作品A
    discovery_scope:
      from_url: https://example.invalid/series/123/episode/200
      through_url: https://example.invalid/series/123/episode/190
```

概念model:

```text
DiscoveryScope
  from_url: str | None
  through_url: str | None

WatchlistTarget
  ...
  discovery_scope: DiscoveryScope | None
```

rules:

- `discovery_scope` がない場合は従来どおりunbounded Discovery
- `discovery_scope` がある場合は `from_url` / `through_url` の少なくとも一方を必須とする
- 指定値はnon-empty URL stringでなければならない
- 既存Watchlistは無変更で読み込めなければならない
- enable / disable等のWatchlist rewriteはscopeを失ってはならない
- YAML直接編集を正式に許可する
- 初期実装ではscope設定専用の新規CLI optionは必須としない

`target.url` は従来どおりDiscovery起点であり、scope boundaryそのものとは限らない。

## 4. Boundary identity

`from_url` / `through_url` のURL文字列そのものをlisting URLと比較しない。各Discovery Adapterが自siteのURL parserを使ってstable external identityへ変換し、listing record identityと比較する。

Boundary判定に以下を使用してはならない。

- `order_key` / `order_label`
- title text
- 最初に現れる数字
- episode numberの推測
- 漢数字変換
- fuzzy matching
- 他siteのmetadata

Adapterはboundary URLが自siteで解釈可能であり、Watchlist targetと同じseries/work/listing scopeに属することを検証する。別site、別作品、別series等が明確になった場合はfail closedとする。

## 5. Canonical discovery orderと範囲意味

各Discovery Adapterはtarget内のstableなcanonical discovery orderを持つ。episode-list型siteでは原則としてincremental Discoveryと同じlatest-firstの論理順を使う。siteのDOM表示順が異なる場合はAdapter内部で正規化してよい。

`from_url` と `through_url` はcanonical discovery order上のinclusive boundaryである。

```text
A
B   <- from_url
C
D
E   <- through_url
F

yield: B, C, D, E
```

one-sided scope:

- `from_url` のみ: from boundaryからcanonical scope末尾まで
- `through_url` のみ: canonical scope先頭からthrough boundaryまで
- 両方: from boundaryからthrough boundaryまで
- 同一identityを両方へ指定: その1 recordだけ

boundary間にbonus、special、前編、後編、分割回等が存在しても、site-native order上で範囲内ならすべて対象とする。内容や話数を解釈して除外してはならない。

## 6. Fail-closed validation

次の場合はbounded runをincomplete/errorとして扱う。

- boundary URLをsite identityへparseできない
- boundaryがtargetとは別scopeに属する
- 必須boundary identityがlisting内に見つからない
- 両boundaryがcanonical order上で逆順
- listing order / identityが曖昧で安全に範囲を確定できない
- siteがbounded Discovery未対応なのにscope付きtargetを渡された

scopeをsilent ignoreしてunbounded Discoveryへfallbackしてはならない。

Discovery Serviceはrecord受信後に逐次Catalogへwriteするため、configured boundaryの不成立が後から判明する可能性がある状態でscope recordをyieldしてはならない。

- `from_url` のみ: from boundaryを確認してからyield開始してよい
- `through_url` のみ: through boundaryの存在を確認するまで対象prefixをbufferし、その後yieldする
- 両方: from / through両boundaryと順序を確認するまで対象rangeをbufferし、その後yieldする
- 必要ならAdapterはrecord / identityを一時bufferしてよい。bounded correctnessをstreaming効率より優先する

これによりboundary typoやlisting changeによる意図外recordのCatalog partial writeを避ける。

Boundary確認後の通常iterator実行中に別のsite errorが発生した場合は、既存Discoveryと同じpartial-refresh semanticsに従い、runをcompleteとして扱わない。

## 7. full / incrementalとの関係

Discovery modeとDiscovery scopeは独立概念とする。

```text
mode:  full | incremental
scope: unbounded | bounded
```

scopeなし:

- 現行full / incremental behaviorを完全維持する

bounded + full:

- configured scope内を完全列挙する
- iteratorが安全にscope末尾まで完了した場合のみ `complete=true`
- 未観測Sourceを `available=false` にするglobal missing-source reconciliationは実行しない
- scope外の既存Source stateには触らない

bounded + incremental:

- Adapterはbounded scope内recordだけをcanonical orderで供給する
- generic known-streak / site-specific incremental stop hookはyield済みrecordに従来どおり適用する
- early stop時は `complete=None`
- 未観測Sourceをunavailableにしない

bounded fullでmissing-source reconciliationを行わないのは意図的な安全策である。scope内だけのmissing reconciliationが必要になった場合は別仕様として追加する。

## 8. Catalog / Batch semantics

bounded DiscoveryはCatalog schemaを変更しない。各recordは既存contractで同期する。

```text
one discovered site record
  -> existing/new Item
  -> Source(site, external_id)
  -> web/default SourceTarget
```

cross-site equivalenceは作らない。同じ `work_key` 配下に内容が実質同一の別site Itemが複数存在してよい。その結果、同じ内容を別siteから複数回crawlする場合があるが、初期仕様では許容する。

Batch Planner / Executorはbounded scopeを解釈しない。Catalogに存在するpending Item / Sourceを従来のsite policyとaccess stateだけで処理する。

## 9. 責務分担

Discovery Adapter:

- boundary URLのparse
- target scope / seriesとの同一性検証
- canonical discovery orderの確定
- boundary identityの探索
- inclusive range抽出
- invalid / missing / reversed boundaryのfail-closed処理
- 必要なbuffering

Discovery Service / common layer:

- WatchlistTargetへscope modelを保持する
- scope付きtargetをAdapterへ渡す
- bounded fullではglobal missing-source reconciliationを抑止する
- 既存external/local state境界を維持する

AdapterはCatalogへ直接read/writeしない。

## 10. Backward compatibility

- scopeなしWatchlist targetの挙動は変更しない
- Catalog schema versionを変更しない
- 既存DB migrationを要求しない
- unbounded fullのmissing-source reconciliationは現行どおり
- unbounded incrementalのknown-streak / stop-hook behaviorは現行どおり
- Batch Planner / Executor / CrawlerRunner contractを変更しない
- Discoveryはexisting Sourceのlocal completed stateを変更しない

## 11. Acceptance criteria / tests

最低限、以下を満たす。

1. scopeなしtargetが既存と同一挙動になる
2. `from_url` only / `through_url` only / both / singletonを表現できる
3. boundaryはsite-native external identityで照合される
4. title / order / episode-number parsingなしでrangeを決定する
5. boundaryはinclusive
6. boundary間の特殊回・分割回もそのまま含む
7. invalid host / URL / different scope / missing boundary / reverse orderがfail closed
8. invalid boundaryで意図外recordをCatalogへpartial writeしない
9. bounded fullでscope外Sourceをunavailableにしない
10. bounded fullでglobal missing-source reconciliationを実行しない
11. bounded incrementalで既存incremental stop semanticsを維持する
12. scope未対応Adapterがscopeをsilent ignoreしない
13. Watchlist rewriteでscopeを保持する
14. Catalog schema versionを変えない
15. Batch / Crawlコードにscope判定を持ち込まない

必要なtest category:

- Watchlist parse / validation / round-trip preservation
- no-scope backward compatibility
- Adapterごとのboth / one-sided / singleton boundary
- boundary間に通常回以外のrecordがあるケース
- malformed / foreign / cross-series / missing / reversed boundary
- boundary validation前にrecordをyieldしないこと
- bounded fullがmissing-source reconciliationを呼ばないこと
- bounded incrementalが既存known-streak / hook契約を壊さないこと

## 12. 将来拡張: cross-site equivalence（deferred）

cross-site重複が運用上大きな問題になった場合でも、最初の拡張はphysical Item mergeではなく、**non-destructive equivalence mapping + explicit human approval** を優先する。

要求:

- original Item / Source graphを移動・削除しない
- 誤対応が判明した場合はequivalence関係だけを解除できる
- automatic fuzzy matchだけでcompletedを伝播しない
- 1:1 / 1:Nを扱う場合もrollbackを容易にする

physical Item mergeはequivalence方式では不足することが実運用で確認された場合のみ再検討する。実装する場合はmergeだけでなく、誤mergeを安全にundo / repairするproduction DB toolingを同時に仕様化する。

この将来拡張は現Phaseの実装対象外である。
