# カドコミ (comic-walker.com) Free-Only Site Adapter — 実装 Runbook

Current maintenance scope (2026-10-13): eleven observed layouts through ten
strict profiles. The earlier `paired_first_double_end` profile is verified on
`KC_011605_S:KC_0116050001200031_E` (第12話-3): paired content from the first
slide, final singleton with PR n=2, then two empty paired main END slides.
It stops at the first END after all source slots and one exact ordinary turn;
the second END stays inactive. Access classification is unchanged. Earlier P4
independent gates below cover the original seven layouts on `KC_004915_S`,
not this maintenance extension. See [PROGRESS](PROGRESS.md) for its local/live
validation and evidence limits. The additional `paired_first_pr_end` profile
was verified on 第12話-2/-1: all paired content, an empty PR n=1 / END n=2
slide, then paired END. The empty intermediate slide is crossed only after all
content, stable exact markers and one guarded ordinary ArrowLeft; completion
requires the following paired END. `paired_first_final_pr` was verified on
第11話-3: pairs, final singleton with PR n=2, paired END and one secondary
recommendation. Both retain strict source, sequence and geometry checks.


Status (2026-10-12): P0/P1/P1.5/P2/P3 and bounded P4 Tester, live-evidence Reviewer, and Lead gates passed for seven observed reader layouts (six strict adapter profiles; the mixed-final profile accepts its two reviewed recommendation forms). Fifteen target episodes and the Episode 22.2 control retest completed through normal CLI Batch/ZIP; the first Episode 22.2 control attempt remains a retained failure with unknown cause. Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope). See [PROGRESS](PROGRESS.md) for exact evidence and limits.
Execution branch: `main` for the direct-entry follow-up; the original Site Adapter phase work used `feat/kadocomi-adapter`.
Site key: `kadocomi`
Sample work: https://comic-walker.com/detail/KC_004915_S?episodeType=first

A third maintenance variant, `direct_first_final_pr`, was verified on
第3話-3/-2 (26227/26228, 20/16 pages). Their first slide has one directly typed
`canvas._root_bx4cr_1[data-type=contents]` inside the unique known beginning root,
which owns no PR marker. It is a real source page, not an empty beginning slide.
It is followed by pairs, a final singleton owning the only main-wrapper PR n=2,
an empty paired main END and one secondary recommendation. The first captured
source is followed by one guarded ordinary ArrowLeft to exact index 1; final
ArrowLeft reaches the paired END, leaving the recommendation inactive.

The native DOM collector recognizes a directly typed canvas only when it is
the sole contents node on the first slide. Adapter acceptance additionally
requires this exact profile and validated beginning ownership/geometry; direct
canvases elsewhere, duplicates or unknown beginning/END topology fail closed.
Native capture still requires the original Blob, full-frame identity draw,
matching source/canvas RGBA, bounded budgets, ordered slots and async stability.
No screenshot/re-encoding fallback or synthetic page is introduced. Native
signature and Python settlement include the direct-first role and owner.

The remaining 29 episodes of this work were inspected structurally; all observed
variants now match strict profiles. This is not a full Batch/ZIP run of all 29.
Five representative live episodes were captured and compared with ordered ZIP
members; other works and a separate independent source observer were not tested.

## 目的と完成形

既存の screenshot_crawler に **現在公開中の無料話のみ** を扱うカドコミ Adapter を追加する。
`Watchlist → discover (full/incremental) → Catalog → batch plan/run → Crawl → manifest/ZIP → Completed`
を、従来のCLI/共通Browser Session/Batch/Packagerの契約で完走させる。
ログイン、購入、チケット/コイン/ポイント/レンタル、アプリ専用コンテンツは対象外。
実サイトで正の根拠が揃った作品と、厳密に検証済みのreader variantだけをサポートする。当初のP4では `KC_004915_S` で7 observed reader layoutsを6 strict profilesにより確認した（mixed-final profileはreview済みrecommendation形式2種を含む）。15 selected targetsとEpisode 22.2 control retestはnormal CLI Batch/ZIPで完了し、post-Discovery/backup、final Reviewer、Lead gateはpassした。22.2の初回control failureは履歴に保持し、原因は未特定。Final documentation review PASS (Reviewer BLOCKING=0; Lead accepted bounded scope)。未観測構造はfail closedにする。

ユーザーからの事前観察（**P0で要再検証**）:
- 作品画面に「全XX話を表示」があり、押すと対象の話一覧が展開される。
- 表示される公開中の各話には「無料」バッジが必ずしも付かない。期限が表示される場合もある。
- 非公開の古い話は「第XX話から第XX話は配信が終了しました」等の文言で表され、各話URLが消える場合がある。
- 単行本・ストア等のリンクが混在する。これらはエピソードとして登録しない。
この4点を**実装上の確定事実・ドメイン全体の保証とみなさない**。P0で公開一覧と実際のViewer進入を比較し、矛盾時はfail closed。

## Authority / 役割 / 実行規則

Authority: `AGENTS.md` → `docs/SPEC.md` → `docs/ARCHITECTURE.md` →
`docs/DISCOVERY_AND_BATCH.md` → `docs/ACCESS_CONTROL_AND_PACING.md` →
`docs/CAPTURE_STRATEGY.md` → `docs/TEST_STRATEGY.md` →
`docs/CODEX_IMPLEMENTATION_GUIDE.md` → `docs/SITE_ADAPTER_GUIDE.md` →
`docs/MULTI_AGENT_SITE_ADAPTER_WORKFLOW.md` → 実装・テスト → Site README/note → このRunbook。
上位authorityと本書が衝突したら勝手に上書きせず、Leadが設計差分・最小修正を明示して解決する。

既存の標準agent構成を使用:
- Lead/root: `gpt-6.1-sol` / `xhigh` — phase契約、証拠判定、整合性、進捗、最終判断。
- Explorer: `site_adapter_explorer` (`gpt-6-luna` / `xhigh`) — read-only調査。
- Implementer: `site_adapter_implementer` (`gpt-6-luna` / `xhigh`) — **唯一のproduction writer**、PoC/実装/テスト/note。
- Reviewer: `site_adapter_reviewer` (`gpt-6.1-sol` / `high`) — material diffを独立レビュー。
- Tester: `site_adapter_tester` (`gpt-6-luna` / `high`) — 必要時に独立live/E2E/画像監査。productionの修正は禁止。

各Phase: Leadが目的/根拠/制約/変更範囲/受け入れ/テストを明示 → 必要なExplorer Probe →
Implementer実行 → Reviewer検証 → BLOCKING修正と再レビュー → Lead checkpoint。
TesterはP2/P4の実画像・end-to-end検証で原則利用する。独立read-only調査だけ並列可。
共有Chromeのoperatorは常に1人。実装前にユーザーの未commit変更を確認し、破棄しない。
`main`へ直接書かずfeature branchで進める。ユーザーの既存作業ブランチも上書きしない。
専用Watchlist/Catalog/output/diagnosticsでlive検証し、通常DBへfallbackしない。
`PROGRESS.md`へ各gateのOBSERVED / INFERRED / UNKNOWN、検証結果、残課題を記録する。

## 不変条件

1. **無料判定**: P1 Discovery/CatalogとP3 PolicyがEligibilityを決める。
   CaptureはCatalogのcanonical episode URLへ1回だけdocument navigationし、
   response、work/episode identity、同一ページのtitle metadata、dialog状態、
   reader readinessを検証する。work pageへの移動や2回目のnavigationは行わない。
   `free_until=NULL`だけでfreeとは判定しない。
2. **履歴**: Source / Item / Artifact / Completedは配信終了後も削除・リセットしない。
   `full` の **completeな全件観測のみ** 未観測Sourceを`available=false`にしてよい。
   `incremental` は既知話境界で通常の早期停止を使い、未観測Sourceを変更しない。
   明示終了行から特定のSource IDを確実に対応付けられる場合だけ、追加の安全な状態更新を検討する。
3. **順序**: サイトの全件リストの oldest→newest の位置が`Source.display_position`のauthority。
   `order_key`、ID、見かけの話数や部分rangeの1始まりだけで番号確定しない。
   終了した過去話を残したまま、再公開で位置が確実に判明したときは再採番を許す。
   不確実な位置を正しいと装って上書きしない。過去の非公開Sourceも衝突検査の対象。
   誤ったprefixを生成するより、要検証/NULL/未変更で停止する。
4. **画像**: `docs/CAPTURE_STRATEGY.md`に従い original bytes →
   source-native pixels / 安全な再構成 → rendered content → screenshotの順。
   原本の安全な帰属を**十分に調査**し、失敗理由を残す。原本JPEG/PNG/WebPは再圧縮しない。
   復元/Canvasのピクセル保存にlossless WebPを採用する場合はRGB/RGBA等の画素一致を証明する。
   単に境界やdraw graphが不明なだけで「原本不可」と断定しないが、アクセス制御/DRM回避はしない。
5. **安全性**: full list / wrong-work / free-state / page identity / spread / ENDが曖昧なら
   `incomplete` / `unknown` / 明示失敗で止める。無限retry・勝手な前話/次話/課金操作禁止。
   正常な本文全ページとENDを確認して初めてZIP/Completedを確定する。
6. **最小変更**: site固有コードを`site_adapters/kadocomi/`とPolicyへ閉じ込める。
   Catalog schema, Core, generic Discovery/Batchの変更は、現行extension pointで解けない
   具体的失敗の再現とLead決裁がある場合のみ。変更時は隣接siteの回帰テスト必須。

## 実行ステージ

1. [P0 — サイト・原画像の証拠収集](P0-research.md)
2. [P1 — Discovery、無料判定、配信状態](P1-discovery.md)
3. [P1.5 — 再公開・履歴を含む位置の安全な再採番](P1.5-position.md)
4. [P2 — Viewer/Capture](P2-capture.md)
5. [P3 — Policy/Batch統合](P3-batch.md)
6. [P4 — 独立E2Eと最終ゲート](P4-verification.md)

P1.5の**高度な過去位置復元はbest-effortでありP3完了の条件ではない**。
ただし、既知の誤採番/衝突/履歴上書きリスクを放置して「P1/P3 PASS」としてはいけない。
復元に証拠が足りないときは、既存位置を保存または新位置をNULLとする安全策を優先し、
その安全策が現行共通Serviceでできなければ、証拠付きの**最小site-neutralな変更**をLeadへ提案する。
完了時の未解決ケースを明確に「制限」として報告する。

## 開始前の実行環境と検証例（実装後）

通常Catalogではなく専用パスを使用する。既存共有Crawler ChromeへCDP接続。
以下は登録済みCLIを専用Catalog/Watchlist/outputへ向ける形の例。

```powershell
python -m screenshot_crawler.cli discover --key kadocomi-sample --mode full `
  --watchlist work/kadocomi/watchlist.yaml --catalog work/kadocomi/catalog.sqlite
python -m screenshot_crawler.cli discover --key kadocomi-sample --mode incremental `
  --watchlist work/kadocomi/watchlist.yaml --catalog work/kadocomi/catalog.sqlite
python -m screenshot_crawler.cli batch plan --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite
python -m screenshot_crawler.cli batch run --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite --output-root work/kadocomi/output --limit 1
```

既存ZIPの番号変更は **Discovery/Batchとは別の明示操作**。
`scripts/renumber_archives.py` が現存し、`Source.display_position`から安全な
preflight/2段階rename/Catalog locator更新を行う。自動実行しない。まずdry-run:

```powershell
python scripts/renumber_archives.py --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite --dry-run
# preflight全結果を確認してから:
python scripts/renumber_archives.py --site kadocomi `
  --catalog work/kadocomi/catalog.sqlite --apply
```

既存の`--work-key`と`--status-dir`も必要に応じて指定。Catalogは実行前にbackupし、
未観測の衝突/復旧不能は停止。ZIP内部の名前・取得済み画像は変更しない。

## 終了条件と最終報告

少なくとも1件、できればビューア構造や期限の異なる2件で、
Discovery → Catalog → Batch → 正しい本文全ページ → END → ZIP → Completedを独立確認。
incomplete/配信終了/誤Sourceは更新や完成処理を誤らない。
関連unit + local Playwright integration + shared変更時の回帰test/Ruffを実行。
`site_adapters/kadocomi/README.md`、対応`note/`、`PROGRESS.md`を同期。
Reviewer BLOCKING=0。未検証・サイト依存・失敗した原画像候補を明記。
報告は変更ファイル、証拠、実行コマンドと結果、スキップ理由、未解決リスク、次の操作まで。

## Current implementation and phase gates

`KadocomiDiscoveryAdapter` is registered in the Discovery CLI registry.
`KadocomiAdapter` is separately registered for manual Crawl and Batch, with
`KadocomiSitePolicy` in the Batch policy registry. For a target with neither
`discovery_scope` nor `archive_order`, the legacy Discovery path accepts the
verified work detail URL on `https://comic-walker.com`, reads the unique
`DIV.EpisodesTabContents_root__* > UL.EpisodesTabContents_episodeList__*`
container, and requires exactly one visible `全{N}話を表示` control. It
requires two identical scoped snapshots 500 ms apart, at the declared row
count, within a 12-second bound before yielding any record. Page-wide
recommendations are outside scope. Rows are buffered and validated before
newest-first emission. This unconfigured path is unbounded and does not infer
global positions. Targets with scope/order use the separate strict
native-history path documented in `note/12_kadocomi.md` and
`site_adapters/kadocomi/README.md`.

Episode source identity is `work_id:episode_id`; persisted reader targets are
canonical query-free episode URLs. The order label comes from the observed
`EpisodeThumbnail_title__` descendant, not publication or deadline dates. On
the legacy unconfigured path no numeric display position is inferred: old
positions stay unchanged and new positions stay NULL. The opt-in native path
uses explicit `episodeNo` positions for observed rows; it does not infer missing
IDs from numeric gaps.

The exact row deadline marker is `配信期限：YYYY/MM/DD HH:MM`. A future explicit
deadline is stored as `free_until`; a later NULL observation clears it. A
no-deadline row was initially classified free only for the independently
verified work `KC_004915_S`; the current site-local policy follows the later
validated public-row convention for works without restriction flags or
deadlines. Expired deadlines remain UNKNOWN.
Access-gate text, unknown deadline syntax, malformed identity, duplicates,
wrong-work IDs, and incomplete counts fail closed. Full reconciliation runs
only after a clean complete list; incremental Discovery leaves unseen Sources
unchanged.

`Work.title` remains initialized from the dedicated Watchlist label because
the shared Discovery service does not apply `DiscoveredItem.canonical_title`.
The adapter validates and exposes the work-page `og:title`; set the Watchlist
label to the actual work name.

P0 evidence and P2 implementation establish a source-native path for the
observed episode 4.1 and first-episode targets: the normal renderer's retained
WebP Blob maps by `currentSrc` to each full-frame identity draw. P2 verifies
every page's Blob provenance, decoded pixels, and stable canvas before
preserving bytes. Tester and Reviewer independently audited all 21 episode 4.1
ZIP members and all 38 first-episode ZIP members against separate live
Blob/canvas evidence; each member was byte-exact and pixel-equal.

P0/P1 retain the exact public-list scope, 53 observed rows, and history/NULL-position safety contract. P3 selects only direct-only free Catalog Sources; current capture opens the exact canonical episode once and validates its main-document response, same-page identity/title metadata, dialog state, and native reader readiness without rechecking the work list. Earlier P4 CLI/ZIP audits for episodes 4.1, first episode, and Episode 79 passed byte/pixel/END review before this navigation follow-up. The direct-entry follow-up passed local Runner/Batch fixtures and independent code/test review. The Episode 22.2 extension passed its bounded anonymous native-source/END probe, local Runner/Batch fixtures, independent code/test review, and normal CLI/ZIP audit. The Episode 20.2 composite layout passed its bounded manual source/END probe, local Runner/Batch fixtures, and normal CLI ZIP; its current 11-page ZIP matched the P0 recorded source hashes and lengths. The existing Episode 4.1 CLI control, final post-Discovery/backup audits, final Reviewer gate, and Lead acceptance also passed. Full prior-suite baseline and current validation are in `PROGRESS.md`.

The original seven observed reader layouts across six strict profiles were verified for their exact observed episode targets on the independently verified work `KC_004915_S`. The observed Episode 20.2 has five paired spreads. Its accepted profile requires the strict owned beginning-PR entry, at least one paired content slide (end index >=3), a final singleton owning main END n=2, the immediate empty paired END, and no trailing recommendation; arbitrary empty starts remain unsupported. The Episode 22.2 beginning-PR topology requires its exact owned marker and one verified ordinary advance; it does not generalize to arbitrary empty first slides. Its normal CLI/ZIP audit and the existing 21-slot Episode 4.1 CLI control passed, as did final post-Discovery/backup audits, Reviewer gate, and Lead acceptance. For the 21-slot control, no fresh per-page source-byte comparison was available; it was validated for ZIP CRC, dimensions, END, Completed, and Artifact. Reader capture evidence remains limited to the exact observed routes and layouts; no-deadline public-row classification follows the current Discovery policy described above and is not additional reader-capture proof. Exact lifetime episode gaps and production archive renumbering are not inferred. The P4 CLI removes temporary source output after packaging, so audits cover ZIP pages, CrawlRun/status, and Catalog Artifact/Completed state, not a retained manifest file. See `PROGRESS.md` for current evidence and validation.
