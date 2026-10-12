# P1 — Discovery / Catalog / 無料状態

Status: PASS — focused/local tests, isolated live full and incremental Discovery,
history-preservation checks, and independent Reviewer gate passed (BLOCKING=0).
See [PROGRESS](PROGRESS.md) for exact counts and the known historical-gap limit.
**目的**: 作品の現在公開中のエピソードのみをSourceとして同期し、
過去Sourceの取得・Completed履歴を保全する。

## 変更範囲

基本: `src/screenshot_crawler/site_adapters/kadocomi/discovery.py`、
最小限のRegistry/CLI wiring、`site_adapters/kadocomi/README.md`、対応`note/`、
Unitおよびlocal Playwright integration fixtures。
Catalog schema変更はしない。Discovery AdapterからCatalogへ直接writeしない。
既存 `DiscoveryService` の拡張は具体的必要が証明された場合に限る。

## 設計契約

1. Watchlist seed: P0で検証した作品詳細URLをまずサポート。
   exact allowlist `https://comic-walker.com` を基本に、ホストalias/形式は実証後のみ。
   work ID、episode ID、canonical URL、query/redirectをstrictに検査。
   Source `external_id` はwork-scoped episode IDの複合IDを第一候補とし、
   衝突/重複/同一episodeのパラメータ違いを正しく扱う。
2. 「全XX話を表示」を展開し、実際のpublic **エピソード一覧スコープ**を全件採取。
   単行本/購入/作品推薦/アプリ/別作品/個人履歴コピーを取り込まない。
   countは「公開リンク数」と「終了区間を含む総件数」の違いをP0で確定し、
   異なる意味の数を直接比較しない。矛盾/未展開/重複/順序不明はincomplete。
3. Discovery Adapterは安全なスナップショットを**全件バッファ・検証後**、
   最新→最古順に `DiscoveredRecord` をyield。
   初期から話一覧が部分表示でも取り逃さない。読み込み中の0件を正常としない。
4. エピソードのみ `kind=episode`; `order_label` はサイトの表示ラベル（第n話/その1/番外編）
   を正規化しながら保存。`order_key` は十分に確実な場合のみ。
   numeric ID/話数の推測から`display_position`を生成しない。
5. `access_mode=free`の判定はP0で証明した公開中の無条件無料状態から。
   明示的に読めない/別権利が必要/不明なものは非eligibleとし、
   読めるという個人sessionの状態だけでfreeとしない。
6. 公開中の**観測された全Source**について、Discovery毎に`free_until`を更新:
   期限あり→正しいaware timestamp、期限表示なし→`NULL`（旧値クリア）、
   `available=true`。観測/取得時刻も従来のフィールドで更新。
   期限のないSourceへ勝手な期限を作らない。期限切れ表示を現時点freeとしない。
7. 明示終了案内を「新しい無料エピソード」として登録しない。
   同じ話のSourceがCatalogに以前存在する場合、そのItem、Source、Artifact、Completedを保存。
   再公開で同一episode IDが再観測されたらSourceを再利用し、`available=true`に戻す。
8. `full`: サイト全件のclean exhaustionかつ`complete=true`の場合のみ、
   同一`discovery_key`内の未観測Sourceを`available=false`。
   削除やCompletedリセットをしない。
   list incomplete時は未観測Sourceのunavailable化を**絶対に**しない。
9. `incremental`: 既存のknown-streak早期停止を原則維持し、
   新しいSourceと観測した既存Sourceを更新。`free_until`は**観測分だけ**更新。
   未観測Sourceの`available`はそのまま。終了区間から個別のSource identityを
   正の根拠で対応付けできる場合だけ、site-specific最小手段をLeadと設計して反映。
   対応付けができない場合は何もせず、次回fullへ委ねる。Incrementalの全件再走査は要求しない。
10. bounded `from_url/through_url` は全体位置・正しい境界が確実に検証できるときのみ
    サポート。未実証なら明示unsupported（違うscopeを勝手にcrawlしない）。
    スコープ内番号を001から振る行為は禁止。取り込み対象のboundaryが消えている場合はfail closed。

## 位置管理との依存

現行 `DiscoveryService` はunbounded fullで観測された現在の話を最古→最新の
1..Nへ振り直し得る。カドコミでは**非公開履歴の位置と衝突する恐れ**がある。
P1のpass判定前に[P1.5](P1.5-position.md)の最低安全策を検討する。
完全な過去位置復元は後回しでよいが、既知の誤採番を静かに保存してはならない。
Catalog位置のauthorityの変更や既存Serviceの任意分岐追加はLeadの承認を要する。

## テスト / 完了条件

- Strict URL、work/episode identity、canonicalization、別作品/volumeリンク除外。
- 「全XX話」遅延展開、総数の意味の違い、欠落/重複/途中停止/矛盾、
  一覧に混じる配信終了案内、順序と番外編/分割話。
- Full 1回目[1,2,3] → 2回目[2,4]は1,3がunavailableでも履歴を保持、
  3回目[1,2,3,4]で同一Sourceを再利用して復活。Completed/Artifact不変。
- Incrementalは観測済みだけ更新し、未観測Sourceを勝手にunavailable化しない。
  期限あり→更新、期限なし→NULL、期限切れ/unknown→非eligible。
- 不完全Fullではmissing sourceをunavailable化しない。
- source ID衝突、同一Catalog Sourceの別Watchlist所属をfail closed。
- 本番の実サイトSnapshot1件 + Unit/Browser fixtureの証拠。
- Reviewer BLOCKING 0。実装時に表示した件数を定数化しない。結果をPROGRESSへ記録。
