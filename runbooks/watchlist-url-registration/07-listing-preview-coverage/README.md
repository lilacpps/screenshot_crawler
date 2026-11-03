# Stage 07 — read-only完全一覧previewのサイト別拡張

> Status: PARTIAL / 3 sites BLOCKED (2026-11-03). Four extensions implemented and independently reviewed; Windows native GUI verified. Final regression evidence is tracked in PROGRESS.md. User authorized Stage07 after Stage06 follow-up `12ce30f`. Existing operational/unrelated changes are protected on feature/watchlist-url-registration.

## Execution contract (2026-11-03)

- Site order follows safe evidence: Piccoma static complete listing, Kadocomi native history, ComicFUZ static work listing, then BookWalker/MangaONE/Hanayume/Younganimal after bounded probes establish complete read-only paths. Unknown/incomplete sites remain visibly blocked; do not claim seven-site completion without proof.
- Reuse existing site parsers, native identities, canonical order and position rules; do not call DiscoveryService.discover or create Catalog state to produce preview.
- Live uses the shared CDP session with dedicated caller-owned Pages, one operator. Static episode/listing metadata GET may be read with scripts/resources blocked, without viewer initialization, reader controls, tickets, grants, purchase or capture. Fixed public list APIs require site-native evidence and exact safe request validation before use.
- Preserve existing unscoped/bounded Discovery and archive behavior. GUI selection must not save unsupported holes: exclusion capability requires same-observation one-shot replay bound to Page/target/scope/time before writes, or explicit rejection of that selection.
- Each site checkpoint requires parser/DOM tests, completeness and foreign identity failures, normal Discovery regression, no-write tests, independent material review, notes and PROGRESS. Shared selection/save changes require affected tests across existing four sites; full suite if the common contract expands materially.
- Windows GUI uses isolated Catalog/Watchlist/runtime, checks draft-only edit, multi-key/work isolation, range/order/segments and final YAML. Never use operational data as a test store. Stage08 is not defined or authorized.

## Objective / scope

- 現行preview対応8サイト: magapoke, jumpplus, zeblack, comicdays, piccoma, hanayume, younganimal, bookwalker。Stage07A/B/Cで4サイトを追加。残り3サイト: comicfuz, kadocomi, mangaone。
- 既存Full Discoveryのcomplete inventoryと、GUIのread-only complete listing previewを混同しない。各siteのpreview_complete_listingでsite-native identity、行ID/順序/position、完全性、境界と除外を検証する。
- siteごとの安全なread-only一覧だけを用い、通常FullによるCatalog write、viewer/reader、チケット/point/購入/権利消費は用いない。過去全件が観測できないなら完全な一覧として扱わない。
- 1サイトずつ既存ListingPreviewService・WorkDraft・SelectionPlannerと連携し、複数keyのscope/archive_order/archive_segmentsをプレビュー・draft-only編集できるようにする。
- URL変換と作品title/IDのmetadata取得はStage 06で扱い、本Stageでは混在させない。ユーザーの利用頻度・実サイト観測可能性を踏まえて対応順を決める。

## Acceptance / tests

- site-native work identityと入力URL/対象keyが一意に結び付く。complete=trueの証拠なしでは保存可能としない。
- 既存range/excluded_external_ids、同site所有重複、archive順序、stale TTL、partial/pagination failureにfail-closed。
- site別Unit＋人工DOM/response Browser Integration＋既存Discovery/WorkEditor/Batch取得担当回帰。必要なら限定Live観測、サイト著作物をテストに保存しない。
- 未対応siteを含む複数key Workは引き続きblocked。安全な正規URLの単一key手動登録はStage 05の条件に従い継続。
- サイトごとにdocs、site note、PROGRESSの実装済み/未確認を更新。全7サイト完了をStage 05の完了条件にしない。

## Current coverage / unresolved contracts

| Site | Stage07 result | Evidence / boundary |
|---|---|---|
| Piccoma | Implemented | Static declared complete count/order/identity; live432rows; one-shot exclusion replay |
| Hanayume | Implemented | Every declared static public range; live249rows; legacy seed requires two matching native identity GETs |
| Younganimal | Implemented | Every public range; live156rows; account-history skeletons excluded only from public preview |
| BookWalker | Implemented, restricted | Single complete page, two count markers, latest-release sort; live11products; exclusion Full validates selected static product metadata before yield |
| Kadocomi | BLOCKED | Proven native123rows have episodeNo gaps15/17/96/102 (range1..127). Current preview/planner/exclusion validator requires contiguous positions. Do not compress native ordinals or claim a partial active DOM is complete. Needs an explicit shared native-gap proof contract plus safe access-classified replay. |
| ComicFUZ | BLOCKED | SSR native34chapters/4groups but no chapter DOM under script denial. The work frontend references WEB_MANGA_VIEWER with useTicket/consumePoint. Do not enable viewer bootstrap to obtain a listing; complete public-list count/terminal/access proof remains unverified. |
| MANGA ONE | BLOCKED | Current SSR is RSC, without legacy chapterList. Public frontend defines read-only GET viewer/chapter_list protobuf; exact request binding/schema/complete pagination/order have not been verified. Do not infer completeness or initialize viewer/server actions. |

BLOCKED sites keep the existing safe single-key registration path. Their URL/title
Stage06 support does not imply complete-list/detail support. These observations
do not change ordinary Discovery or assert that normal acquisition is broken.
Full suite/native GUI verification is tracked separately in PROGRESS.md.
