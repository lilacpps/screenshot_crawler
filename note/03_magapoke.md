# 03. Magapoke

## Purpose and scope

`MagapokeAdapter` crawls one episode through the shared Crawler Chrome/CDP
session. Magapoke Discovery is implemented separately for episode-list
enumeration and Catalog synchronization. Batch and SitePolicy support free and
active-rental direct access, one Work Ticket candidate per Work, and a
sequential account-global Premium Ticket pass. Login and all paid fallback
behavior remain out of scope.

## Current Batch behavior (M3c1 and M3c2)

- Magapoke Batchのarchive stemは通常のepisodeでは従来名を維持する。同一Work内で、全statusのCatalog Itemを対象に、packagingの`archive_stem()`でdisambiguatorなしに生成したbase stemが重複する場合だけ、collision groupのpending candidateへ`magapoke-{Source.external_id}`を設定する。completed Itemも判定対象だが、通常Batchのcandidateには含めない。既存ZIPがある場合のpackaging `FileExistsError` と自動renameなしの安全性は維持する。

- Catalog schema v4 stores nullable `sources.published_at`. This is the
  Magapoke-observed publication date for that Source, not an Item property.
- The live row date selector is `p.c-episode-item__date`; the observed text
  format is `YYYY/MM/DD`. A date-only observation is normalized to JST midnight
  (`+09:00`) for stable ordering; it does not claim that publication occurred
  at midnight. Missing or malformed dates remain NULL without making Discovery
  incomplete.
- Magapoke `order_key` remains `None`; `published_at` is priority metadata only.
- Batch candidates run direct access first. This includes free episodes and a
  quota source with a future observed `access_granted_until` (`active_rental`).
- An ungranted quota source is a Work Ticket candidate with
  `quota_resource="work_ticket"`, `quota_scope="work"`, `quota_limit=1`, and
  `quota_commit_mode="after_observed_consumption"`. The Planner groups by Work,
  selects its oldest dated pending candidate first, puts NULL dates last, then
  uses existing stable item ordering and source ID as ties. Work pass order is
  `Work.created_at`, then `Work.id`.
- The visible page is the final authority on resource eligibility. Work Ticket
  and Premium Ticket have separate exact text/class checks and click paths.
  Neither resource falls back to the other. Points, coins, subscriptions, and
  unknown purchase controls are never clicked. A Premium-only screen during
  Work Ticket pass is `work_ticket_unavailable`; a Work-only screen during
  Premium pass is `premium_ticket_unavailable`.
- Existing viewer content is entered without a ticket click. Consumption is
  reported only after the unique Work Ticket click, control disappearance, and
  viewer canvas content are all observed.
- `quota_started_at` is written only after observed consumption, using the
  Adapter's aware click/entry timestamp. Magapoke records a conservative
  `access_granted_until` at `consumed_at + 71 hours`. Both are saved before
  packaging and remain recorded if crawling then fails. Unavailable and
  already-accessible cases do not record quota state.
- M3c2 adds a `premium_ticket` resource pass after the complete Work Ticket
  pass. It concentrates Premium candidates in the oldest Work first, and
  re-reads the live semantic balance before every click. The balance is never
  written to Catalog. A displayed zero stops the Premium pass.
- Premium Ticket access uses the same conservative `consumed_at + 71 hours`
  grant as Work Ticket. The complete Premium path, including that grant,
  was live-verified on 2026-09-23.

## M3c2 Premium Ticket contract

- `premium_ticket` is account-global external state. No balance is stored in
  Catalog. Batch runs Premium only after completing all direct and per-Work
  Work Ticket candidates, then replans against current pending Catalog state.
- Premium pass orders `Work.created_at ASC`, `Work.id ASC`, then source
  `published_at ASC` (NULL last), existing item order, and `source_id DESC`. It keeps
  all selected candidates for an older Work together before moving to a newer
  Work.
- Before each Premium click, the Adapter reads one exact semantic balance row:
  `dl.p-episode-purchase__point`, normalized `dt` label
  `プレミアムチケット`, and `dd` value matching `N枚`. Header count is not
  authoritative. A missing, duplicate, malformed, or structurally ambiguous
  balance fails closed. `0枚` yields `premium_ticket_exhausted`, does not click,
  and stops the Premium pass. A known Work-only screen yields
  `premium_ticket_unavailable` and leaves the Item pending.
- Consumption is reported only after the requested ticket action disappears
  and viewer canvas content is observed. Executor persists the existing
  conservative 71-hour source grant after observed consumption, including
  crawl failures. Premium's use of the same 71-hour grant as Work Ticket is
  now live-verified for the tested production path.

### M3c2 Premium Ticket live verification (2026-09-23)

- Target: `title_id=00002`, episode `305886`, using a temporary Watchlist and
  temporary Catalog. This was the same Work in which episode `310045` had
  already consumed a Work Ticket during M3c1 verification, so the Work Ticket
  was still charging and the target episode exposed Premium-only entry.
- The initial Batch pass selected `305886` as a `work_ticket` quota candidate.
  The live page correctly returned `work_ticket_unavailable`; no Work Ticket or
  Premium Ticket was clicked in that pass and the Item remained pending.
- Batch then re-read Catalog and created the `premium_ticket` resource pass.
  With `--limit 2`, the Work Ticket attempt consumed the first attempt slot and
  the Premium attempt consumed the second. A preliminary run with `--limit 1`
  therefore stopped normally after `work_ticket_unavailable`; this confirms
  that expected resource-unavailable skips count as execution attempts for the
  global Batch limit.
- The Premium pass observed the semantic Premium Ticket balance, clicked the
  unique exact Premium Ticket control once, confirmed viewer content, and
  recorded `AccessConsumption(resource="premium_ticket")`. The observed balance
  decreased by one ticket.
- The same Premium run continued through page capture and packaging without a
  second resource click. The Item completed successfully and a ZIP artifact was
  produced.
- Catalog recorded `quota_started_at` from the observed Premium consumption and
  `access_granted_until = consumed_at + 71 hours`, confirming that the
  conservative grant used by production matches the tested Premium rental path.
- This verifies the intended M3c2 sequence end-to-end:
  `work_ticket_unavailable` -> Premium re-plan -> one Premium Ticket consumed ->
  viewer/crawl completion -> quota/grant persistence -> ZIP packaging.

## M3c1 Work Ticket entry readiness and live findings (2026-09-22)

- The first live Batch attempt for `03294` / episode `442501` failed before
  clicking with `Magapoke Work Ticket entry UI is unknown or ambiguous`;
  `quota_started_at` and `access_granted_until` remained NULL. No resource was
  consumed in that attempt.
- After the readiness/classification fix, a subsequent user-run Batch attempt
  reported that the Work Ticket was consumed, then failed with
  `Adapter operation timed out: initialize`. The output run directory was empty,
  so no screenshot or manifest was written. The resolved `$Catalog` path was not
  available in this checkout to verify that run's quota fields.
- Read-only inspection confirmed an initial-load race: immediately after
  `goto(..., wait_until="commit")`, the purchase panel and controls were absent;
  the panel became available within about one second. The `.c-viewer` wrapper
  could appear before any canvas existed, so it alone does not establish access.
- In the stable panel, the Work Ticket anchor retained the expected exact label
  and `.c-btn-icon-primary--ticket` class. The same panel also contained a
  comment anchor in a separate `.p-episode-purchase__btn`, with
  `.p-episode-comment-btn` and a comment-navigation href. The broad panel-wide
  anchor/button selector therefore counted a non-access navigation link; the
  Work Ticket text/class contract itself was still valid.
- Entry now polls at bounded intervals until canvas content is usable, visible
  access actions can be classified, or `page_change_timeout_ms` expires. A
  visible `.c-viewer` wrapper without canvas content is not treated as access.
  Only the known comment navigation anchor classes/hrefs are excluded from
  access-action classification. Unknown visible actions remain fail-closed.
  Ticket click and `AccessConsumption` confirmation semantics are unchanged.
  Runner allows Magapoke initialization up to five bounded page-change windows
  plus the Core grace, so readiness, ticket confirmation, and viewer setup are
  not cancelled by a single 12-second outer deadline. Other adapters keep their
  existing initialization budget.
- The first investigation used read-only navigation and consumed no resource.
  Codex did not click a live Work Ticket to verify this code fix; the later
  consumption was reported from the user's Batch run.
- The user later confirmed a successful M3c1 live run for
  `00002/310045`: `quota_started_at=2026-09-22T22:25:33.703444+09:00`,
  `access_granted_until=2026-09-25T21:25:33.703444+09:00`, Item completed,
  CrawlRun succeeded with 42 pages and `next_content`, and a present ZIP
  artifact of 9,935,703 bytes. This verifies Work Ticket click through
  consumption recording, continued scanning, packaging, and completion.

## URL and context

The supported identity is `/title/{title_id}/episode/{episode_id}`. The URL
strings are preserved: `work_id=title_id`, `episode_id=episode_id`,
`content_id=episode_id`, and `chapter_id=None`. A change to another episode is
`NEXT_CONTENT`; the adapter does not navigate back.

## Viewer structure and mapping

The content target is `.c-viewer__comic canvas`. In the live viewer, an
`OffscreenCanvas` first receives the complete CDN JPEG and then receives tile
`drawImage()` calls. The visible canvas receives the completed OffscreenCanvas.
The final visible-canvas draw is recorded separately. Native reconstruction is
accepted only when that draw is also a full-size 1:1 identity draw with the
expected source/destination geometry, transform, composite operation, and
filter. A later crop, scale, flip, or other renderer change therefore falls
back to a screenshot.

`prepare_page()` installs a bounded, metadata-only hook before navigation. It
records source path/type/dimensions, source and destination rectangles, the
canvas backing size, transform, composite operation, filter, and sequence.
The hook performs no encoding, base64 conversion, hashing, network access, or
pixel copying. The latest render generation is copied when it is drawn to the
visible canvas. Network response arrival order is never used as page order.

The production path uses the mapping observed for the current source object;
it does not assume 4x4, 16 tiles, a fixed permutation, or divisible image
dimensions. The sampled live pages used 16 tile calls with 168x256 rectangles
on a 685x1024 source, leaving a 13px right edge from the initial full draw.

## Capture strategy

The CDN JPEG is a scrambled transport image, not a finished page. It is never
saved directly and is never pixel-decoded/JPEG-reencoded.

```text
scrambled CDN JPEG
    -> validate source/episode, JPEG structure and observed mapping
    -> verified quantized-DCT block permutation
    -> lossless reconstructed JPEG
    -> if coefficient path is unsafe/unavailable, verified pixel reconstruction PNG
    -> if both native paths are unsafe/unavailable, canvas Locator screenshot PNG
```

The reconstruction starts with the decoded full source and pastes the
verified tile crops into the observed destination rectangles. This mirrors
the viewer's initial full draw and preserves an uncovered edge strip. It
requires integer, equal-size source/destination rectangles, identity
transform, `source-over`, `filter=none`, bounded coordinates, non-overlapping
source/destination coverage, and complete inferred tile extents. Missing,
ambiguous, overlapping, gapped, scaled, transformed, invalid, or undecodable
input falls back without stopping the crawl.

The production coefficient path uses the normal `jpeglib>=1,<2` dependency and
is implemented in `native_capture.py`; the diagnostic reference remains in
`poc/magapoke_lossless_jpeg.py`. It does not decode pixels or JPEG-reencode
them. It is enabled only for grayscale or three-component 4:4:4 JPEGs where
every component has 1x1 sampling, every observed source/destination rectangle
is 8x8 aligned, the base/final draws are full-size identity draws, and
coefficient/header/edge validation succeeds. The mapping is calculated from
the observed rectangles; no fixed tile count or permutation is assumed.
4:2:2 and 4:2:0 are rejected rather than assumed safe.

The Adapter keeps the existing source-body retry of two additional attempts.
It also allows two additional capture attempts for the current visible spread
when observation is transiently incomplete: rows, mapping/base/final draw
metadata, canvas dimensions, or source JPEG bytes are not ready. Each attempt
re-observes all visible rows and keeps the spread all-or-none. A deterministic
unsafe mapping or a successful PNG reconstruction is not retried; the latter
returns PNG immediately. After the bounded attempts, the existing PNG then
Locator fallback remains unchanged.

The artificial 70x48 fixture verified forward and inverse coefficient
permutation, including a 72px coded width with the rightmost coded block left
untouched, and matched the existing PNG reconstruction at every decoded RGB
pixel. A live run from episode 244815 verified five 685x1024 artifacts. All
five were baseline grayscale JPEGs with one Y component at 1x1 sampling; the
16 observed tiles cover 0..671 and the two coded block columns covering the
right edge remained unchanged. Per-component coefficient arrays, quantization
tables, Huffman tables, dimensions, and decoded pixels all validated. The
reconstructed JPEG was 0.998488--0.999121 of the source JPEG and
0.199810--0.236303 of the existing PNG size.

`jpeglib.write_dct()` changes the JPEG container: it duplicates the JFIF APP0
marker and can renumber component IDs (for example, live grayscale ID 1 to 0),
while retaining the tested quantization/Huffman tables and live image pixels.
The production validator requires source APPn/COM payloads to remain present,
and exact dimensions, sampling, quantization, DQT/DHT/DRI payloads, progressive
mode, coefficient arrays, and untouched right-edge blocks. It does not promise
bit-for-bit JPEG container preservation.

## Page identity and navigation

Identity combines the visible canvas page index and current source path. The
source path is used only as a current-page identity signal, not as response
arrival order. The next operation clicks `.c-viewer__pager-next` once. A
bounded `wait_for_change()` waits for either identity, URL change, or the
viewport-visible and stable `.c-viewer__last` terminal card. A newly visible
captureable canvas/content identity takes priority over the terminal card, so
a transitional viewport containing `[final comic page] [terminal card]`
captures the comic page first. The terminal card is an `END` for the current
episode only when no current captureable content is available; its `次の話を読む`
`.c-viewer__page-btn` is not clicked, so the next episode is not entered or
captured. A terminal card that exists only in the DOM or outside the viewport
is not an `END` signal. A URL change from episode 244815 to 244816 remains a
normal `NEXT_CONTENT` completion and 244816 is not captured.

## Output metadata

Title and order are read from the page title where available. Author is
currently unavailable and genre is `漫画`. Native reconstruction artifacts are
JPEG when the coefficient path is safe, otherwise PNG at the canvas backing
dimensions (the live target is normally 685x1024).

## Browser session

The adapter receives a Playwright `Page`. It does not launch Chrome, select a
profile, resolve a CDP endpoint, or manage browser lifecycle. Use the shared
`.chrome-crawler/` profile and `CRAWLER_CDP_ENDPOINT` through the common CLI.

The CLI closes the crawl Page and disconnects the Playwright/CDP session before
filesystem-only ZIP packaging. This prevents late viewer/CDP events from
writing to a transport that is already being torn down.

## Discovery investigation (M0)

### Target

- URL: `https://pocket.shonenmagazine.com/title/00695/episode/244815`
- Investigation date: 2026-09-22.
- Latest `main` checked before the investigation: `63dc2d8` (`Retry transient Magapoke capture observations`).
- The shared Crawler Chrome was reached through CDP at the standard local endpoint `http://127.0.0.1:9222`; an existing account session was visible through the page header (`マイページ` and account counters). Cookies and storage were not inspected.
- The requested precondition said that episode `244815` was already in ticket-rental state. The live DOM contradicts that mapping: `244815` currently displays `【第１話】「一眼一足」（１）` with the free signal. The live row matching the requested title `【第７話】「鋼人攻略戦準備」（１）` is episode `244841`, and that row is the one displaying `レンタル中`. This ID/title discrepancy must be resolved before production Discovery is implemented.
- Only navigation/reload of the supplied episode page and the visible `もっと見る` list expansion were used. No episode row, ticket, point, purchase, subscription, or other paid/quota control was clicked.

### Episode list structure

- The work title is `h1.p-episode__comic-ttl` (`虚構推理`). The observed `data-v-*` attributes are Vue build output and are not suitable as primary selectors.
- The episode-list section is the `div.p-episode__sec` containing `.p-episode__list` and `ul.c-episode-items`. In the observed build it also had `data-v-d2021e79`, but the class/structure is the stronger signal.
- A row is `ul.c-episode-items > li.c-episode-items__item > a.c-episode-item`.
- The canonical row fields are:
  - episode link: `a.c-episode-item[href]`; observed hrefs are `/title/00695/episode/{episode_id}` and resolve to the same-site absolute URL;
  - title: `h2.c-episode-item__ttl`;
  - date: `p.c-episode-item__date`;
  - access indicator: `.c-episode-item__ico` and its state suffix class;
  - optional rental remaining time: `.c-episode-item__label02-txt` / `.c-episode-item__txt--renting`.
- After expansion, 259 visible rows were observed. The episode IDs were unique; no duplicate row identity was found. `title_id` is safely preserved as the string `00695`, and `episode_id` is safely obtained from the href path without using the displayed title.
- The list is newest-to-oldest. The first rows were episodes 103, 102, 101, and the final rows were episode 1. Episode 7 appeared as IDs `244844` through `244841`, with part 4 first and part 1 last.
- Raw titles are not a simple integer order domain. The observed list contains `(1)` through `(5)`, full-width and ASCII digit variants, `前編`/`後編` in the title, and `【特別編】TVアニメBD1巻 特典漫画`. Keep the raw title as `order_label` input; do not assume that a single integer is a safe `order_key`.

### Expand behavior

- The episode-list control is a visible `button.p-episode__more-btn` inside the same `.p-episode__sec` / `.p-episode__more` scope. It had text `もっと見る`, `disabled=false`, and no href. There were hidden buttons with the same class in other page sections, so visibility and episode-list scoping are required.
- In this live observation the initial visible row count was 10. One click changed it from 10 to 160; a second click changed it from 160 to 259. The existing first row and the `ul.c-episode-items` node remained connected, while 150 rows were added as child-list mutations on the first expansion. No pagination navigation or scroll was required.
- The safe traversal shape is therefore: collect the current identity signature; find exactly one visible episode-list `もっと見る`; click it; bounded-wait until the identity signature changes; reject no-progress; repeat. The control should be re-selected after every mutation rather than reused.
- Full expansion was observed when the identity count reached 259 and no visible episode-list `button.p-episode__more-btn` remained. Hidden same-class buttons elsewhere in the page must not be treated as evidence that the episode list is incomplete.
- A future implementation needs bounded `max_expand_attempts`, a bounded per-click wait, and a no-progress guard. The live observation supports progress by identity-count/signature change, not a fixed click count.

### Access-state observations

The following counts are account/time-dependent observations from the fully expanded page, not fixed site constants: 3 `--point`, 225 `--ticket-free`, 30 `--free`, and 1 `--renting` row.

| Observed state | DOM signal | Example | Investigation result |
| --- | --- | --- | --- |
| free | `.c-episode-item__ico.c-episode-item__ico--free` containing `<img src="/img/txt_free01.svg" alt="無料">` | `244815` | Strong list-level signal; no point/ticket text. |
| quota/ticket candidate | `.c-episode-item__ico.c-episode-item__ico--ticket-free` containing the same `alt="無料"` asset | `244842` | The class distinguishes it from `--free`, but the page does not say `ポイント` or `チケット`; the exact quota semantics were not verified by clicking. |
| active rental | `.c-episode-item__ico.c-episode-item__ico--renting` with `<img src="/img/txt_renting01.svg" alt="レンタル中">`, plus `.c-episode-item__txt--renting` | `244841`, `【第７話】…（１）` | Confirmed at DOM level. The visible row text contained `あと71時間`; `レンタル中` was in the image `alt`, not `innerText`. No expiry timestamp or data attribute was found. |
| paid/point required | `.c-episode-item__ico.c-episode-item__ico--point` with visible text `90` | `443536` | Strong class/text signal; the row did not contain the literal word `ポイント`. No paid control was clicked. |
| owned/purchased | No verified list signal | — | Not verified. `is-read` / `is-last-read` only indicate reading/current-row history and must not be treated as ownership. |

Color was not used as a state contract. The useful signals were the state-specific class and the semantic image `alt`; however, no `data-*`, `aria-label`, or `data-testid` state attribute was observed. The `--ticket-free` versus `--free` distinction remains a site-specific class contract that should be treated as a monitored observation, not silently generalized.

### Proposed Discovery mapping

- Work identity: `title_id` from the target/list URL, preserving leading zeroes (`00695`).
- Source `external_id`: the `episode_id` path segment, for example `244841`; do not derive it from the title string.
- Source target URL: the canonical absolute episode URL, for example `https://pocket.shonenmagazine.com/title/00695/episode/244841`.
- Item metadata: work title from `h1.p-episode__comic-ttl`; raw episode title from `h2.c-episode-item__ttl`; raw date from `p.c-episode-item__date`; order normalization is intentionally not implemented by M0.
- Tentative access-mode candidates for a future adapter are `--free` → free, `--ticket-free` → quota/ticket candidate, `--renting` → active rental, and `--point` → paid/points. These are observations for a future Site Policy mapping, not an implementation decision in M0. They must not be confused with the crawler `access_strategy`.

### Full traversal completion

`complete=true` is safe only when all of the following hold:

- the episode-list section and work title are found unambiguously;
- every emitted row has a same-work episode href and a non-empty `episode_id`;
- every expansion click has a bounded wait and increases the identity signature/count;
- the visible episode-list expand control is absent after the final progress check;
- no navigation, timeout, selector ambiguity, or DOM observation error occurred;
- optional sanity checks, such as the observed row count matching the page's `全259話` count, do not conflict.

The future adapter should return an incomplete result rather than claim completion if the selector is missing/ambiguous, a row lacks identity, a click produces no progress, a control remains visible after the attempt bound, or the page/navigation state is otherwise unclear. A hidden button in an unrelated section is not a failure.

### Incremental outlook

Generic known-streak is usable as the incremental stop mechanism, with one adapter-level traversal requirement: yield the newest-to-oldest episode-list order and treat the initial newest block as the traversal prefix. The page initially renders a newest block plus an older tail, then inserts the middle/older rows when `もっと見る` is expanded; an iterator must not mistake that presentation detail for a normal contiguous page boundary. No Magapoke-specific stop hook is indicated by the observed ordering. The generic known-streak limit and Catalog safety behavior remain framework responsibilities.

### Open questions

- The requested URL/ID and the requested title do not match live data (`244815` is episode 1; `244841` is episode 7 part 1 and is the active rental row). Confirm the intended watchlist target before implementation.
- `--ticket-free` is a strong DOM candidate for the work-ticket/quota state, but the exact resource semantics were deliberately not verified by clicking.
- Owned/purchased state was not verified and should remain unknown until a non-consuming, explicit signal is found.
- Rental expiry was observed only as human-readable `あと71時間`; no absolute expiry or hidden dataset value was found.
- The class names and image paths are site/build-specific and may change. No stable `data-testid` or state data attribute was observed.
- M0 did not implement `MagapokeDiscoveryAdapter`, registry changes, Site Policy, Batch, access strategies, or any Catalog/Core change.

## Discovery implementation (M1)

M1 implements `MagapokeDiscoveryAdapter` and registers it under the
site-neutral `discover` CLI registry. A Watchlist target may be any supported
episode URL; the target episode's displayed title or access state is not used
to decide whether the work can be discovered. The target path supplies the
work `title_id`, while every discovered `episode_id` and URL comes from that
row's own `a.c-episode-item[href]`. Leading zeroes in `title_id` are retained.

The adapter uses the following observed selectors:

- work title: `h1.p-episode__comic-ttl`;
- unique episode-list scope: visible `div.p-episode__sec` containing both
  `.p-episode__list` and `ul.c-episode-items`;
- rows: `ul.c-episode-items > li.c-episode-items__item > a.c-episode-item`;
- row title: `h2.c-episode-item__ttl`;
- access indicator: `.c-episode-item__ico` and its state suffix class;
- expansion control: visible `button.p-episode__more-btn` inside that same
  episode-list section.

Both full and incremental discovery first expand the complete list, then
validate every row and construct the records before yielding any item. Each
click is bounded and the control is re-selected after DOM mutation. Progress
requires a larger episode identity set with all previous identities retained;
no-progress, timeout, attempt-limit, selector ambiguity, wrong-work rows, and
duplicate `episode_id` values raise `DiscoveryIncompleteError`. Hidden
same-class controls in unrelated sections are ignored. Successful records are
yielded in the observed newest-to-oldest DOM order.

The M1 access mapping is:

| DOM class | Catalog `access_mode` |
| --- | --- |
| `.c-episode-item__ico--free` | `free` |
| `.c-episode-item__ico--ticket-free` | `quota` |
| `.c-episode-item__ico--renting` | `quota` |
| `.c-episode-item__ico--point` | `paid` |
| no recognized state suffix | `unknown` |

Conflicting recognized state classes are incomplete. Mapping active rental to
`quota` does not create or update `quota_started_at` or
`access_granted_until`; M1 has no Batch or active-grant operation. Ownership
remains `unknown` unless a future explicit, non-consuming signal is verified.
Each item uses the work title as `canonical_title`, `genre="漫画"`,
`kind="episode"`, `order_key=None`, and the raw episode title as
`order_label`. Each source uses `episode_id` as `external_id`, the canonical
episode URL, `available=True`, and no local expiry.

The M0 live ID/title discrepancy (`244815` versus the observed episode-7 row
`244841`) is not a production Discovery blocker: the target is only the work
scope entry point and row identity is always taken from each row href.

Generic known-streak remains the incremental stop mechanism. Because the
adapter yields a fully expanded, validated newest-to-oldest sequence, no
Magapoke-specific stop hook is needed. M1 does not add Batch/SitePolicy,
`access_strategy` handling, ticket or point clicks, active-grant persistence,
or Catalog/Core schema changes. The current generic known-streak threshold is
five consecutive distinct known identities; a new source resets the streak.

### M1 live verification

On 2026-09-22, the M1 CLI was run against the shared Crawler Chrome at
`http://127.0.0.1:9222` with a temporary Watchlist and temporary Catalog. The
target was the supplied episode URL `.../title/00695/episode/244815`; no
episode row or paid/quota control was clicked.

- full discovery completed with 259 observed sources and
  `stopped_reason=exhausted`;
- the live page currently exposes two `.p-episode__list` columns inside the
  same episode section, so the adapter treats the unique section as the
  listing scope and validates all descendant `ul.c-episode-items` rows;
- Catalog access modes were `paid=3`, `quota=226`, and `free=30`; the former
  M0 active-rental observation (`episode_id=244841`) is represented as
  `quota` without local grant timestamps;
- the initial M1 live verification was performed while the generic threshold
  was 2, so its incremental run observed two already-known newest rows and
  stopped with generic `known_streak` (`complete=None`); current code uses 5;
- Catalog export showed 259 items, 259 sources, and no crawl runs or artifacts.

The temporary Watchlist and Catalog were removed after verification. The
live counts are observations only and are not production constants.

## Batch implementation (M2)

M2 adds `MagapokeSitePolicy` to the existing site-neutral Batch Planner and
Executor path. The policy is deliberately free-only:

| Catalog state | Policy result |
| --- | --- |
| `free` | eligible, `direct`, `consumes_quota=False` |
| `quota` | skipped, `quota_not_supported` |
| `paid` | skipped, `paid` |
| `unknown` | skipped, `unknown` |
| `owned` | skipped, `owned_not_verified` |
| unavailable | skipped, `unavailable` |

`MagapokeAdapter.configure_run()` accepts `auto` and `direct`, and rejects
`quota` before navigation. Direct execution uses the existing viewer flow;
M2 adds no ticket, premium-ticket, point, quota, or reader-entry click. The
Batch Executor therefore preserves NULL `quota_started_at` and
`access_granted_until` for free runs. Quota/renting handling, ownership, and
all grant persistence remain deferred to M3.

## Tests and live verification

Unit tests cover URL/context, response filtering, JPEG magic/dimensions/MCU
inspection, coefficient-domain aligned tile permutation, non-divisible PNG
tile permutation, missing/overlap/gap and unsafe mapping rejection. The local
Playwright fixtures cover the complete Adapter-level hierarchy: an aligned
fixture returns coefficient-domain JPEG, while the existing non-aligned and
bad-header fixture exercises PNG reconstruction and Locator screenshot
fallback. Unit tests also cover retrying a transient spread observation once
and avoiding retry for deterministic failure. They also cover tainted canvas
screenshot behavior through Core and episode URL change.

The real-site CDP smoke on 2026-09-21 captured 25 artifacts from episode
244815, all as JPEG at 685x1024 through the coefficient path, and packaged them
successfully. The run stopped at `NEXT_CONTENT` after navigating to episode
244816 without capturing it. A prior PNG smoke remains the fallback reference.
Representative first/middle/end comparisons were made against Locator
screenshots; the native results have the same orientation, panel order, and
crop. The sampled live mapping remained 16 tiles with 8x8 JPEG MCUs. Do not
report the former raw-JPEG smoke result as valid for this reconstruction
implementation.

## Known limitations

Only the observed HTMLImageElement -> OffscreenCanvas renderer path is accepted
for native reconstruction. ImageBitmap/unknown source objects, complex
transforms, filters, composites, incomplete mapping, and missing response
bodies use screenshot fallback. The mapping is intentionally bounded to the
current render generation; a future renderer change should fail safe rather
than infer a new permutation.

## M3a quota investigation (2026-09-22; safely stopped)

### Target and live precondition

- Latest `origin/main` checked before investigation: `120c550` (`Add Magapoke free-only Batch support`); the local `main` was at the same commit.
- Target work: `title_id=01367`, `ギルティサークル`; supplied entry `.../episode/319720`.
- The shared Crawler Chrome CDP endpoint `http://127.0.0.1:9222` was available (Chrome 152). The specified episode page loaded in the existing browser context; no cookies or storage were inspected.
- The page initially rendered 10 rows. The episode list was expanded in two visible `もっと見る` actions, with counts 10 → 160 → 274. Final DOM order is newest-to-oldest. The target rows were at the old end of the list: `320359` at DOM index 271 (zero-based), then `319721`, then `319720` at index 273.
- Live row observations: `319720` = `【第1話】上京物語`, `.c-episode-item__ico--free`; `320359` = `【第3話】ヤリサー`; `320474` = `【第4話】星見さんの秘密`. On the initial 10-row observation, `320359` and `320474` showed `.c-episode-item__ico--ticket-free`. After full list expansion, `320359` showed `.c-episode-item__ico--renting`, `alt="レンタル中"`, and `あと71時間`.
- No episode row or access control was clicked during this investigation. The change in observed `320359` state occurred without a crawler click. Because the fully expanded/current state was already renting, the mandated stop condition applied. No further ticket-state, rental, 320474 viewer, header, or My Page investigation was performed.
- The final full-list row snapshot existed only in the temporary diagnostic process and was not persisted before the fail-closed stop. Therefore the complete 274-row `(episode_id, raw title, DOM order, access class)` inventory is not available in this note; only the count/order and target rows above were retained. Do not treat the list inspection as complete inventory evidence.

### Resource-safety outcome

- Work Ticket click count: **0** (the allowed one-time click was not used because `320359` was already renting).
- Premium Ticket click count: **0**; Premium Ticket was not consumed.
- No point purchase, subscription, or other resource-changing operation was performed.
- Premium Ticket balance/count, expiry display, header selectors, charge details, and the `320474` access UI remain **unobserved** in M3a. No selector or parsing contract is established for Premium Ticket balance.
- Work Ticket vs Premium Ticket controls, exact labels, roles, enabled states, and safe locators remain **unverified**. Do not implement a click fallback based on this investigation.
- The rental observation `あと71時間` is human-readable only; no absolute expiry or hidden timestamp was inspected. It must not be converted into a production expiry timestamp.

### M3a design findings and recommendations (provisional)

- Keep Magapoke `order_key=None`; use the raw displayed episode title for `order_label`. Do not synthesize an order key from DOM position.
- Keep quota priority separate from catalog order metadata. The observed full list is newest-to-oldest, so reverse observation/insertion order is a candidate oldest-first strategy only if the Catalog preserves discovery insertion order for each work. Validate the actual Source/Item identifier and insertion semantics before relying on descending IDs; a discovery-order change would change this heuristic. No evidence here establishes that `Source.id` alone is a durable chronology contract.
- Treat oldest-first as a Batch preference only, never as a site-enforced eligibility rule. The live snapshot included ticket-free rows for episodes 3 and 4, but episode 3 was already renting when the fully expanded state was inspected; no ticket was consumed to test eligibility.
- Provisional M3b direction remains: a confirmed active `--renting` grant should use direct episode navigation with `consumes_quota=False`, without a resource button click. Persist an absolute `access_granted_until` only if a trustworthy absolute timestamp is later observed; `あとNN時間` alone is insufficient. M3a did not reload the rental URL, so direct viewer access remains unverified.
- Provisional M3c direction remains per-work Work Ticket first and account-global Premium Ticket allocation second, with oldest-first as a crawler preference. This investigation did not observe either balance or either access control, so exact controls, availability checks, charge state, and allocation counts still require a safely eligible live episode and fresh explicit verification.
- `order_key`, Discovery, SitePolicy, Adapter quota behavior, Batch Planner/Executor, Catalog schema, and production ticket code were not changed.

### Remaining investigation

- Re-run only after confirming `320359` is not already renting and the logged-in session is expected. Before any one-time Work Ticket use, verify the exact currently visible Work Ticket control is unique and distinct from Premium Ticket and point-purchase controls; otherwise stop without clicking.
- Capture and retain all expanded row identities/titles/classes before any mutation.
- Observe Premium Ticket count before and after any authorized Work Ticket use, including hover-triggered viewer/header content; inspect My Page only if viewer/header does not expose a stable count. Record expiry buckets only if plainly present.
- After a permitted Work Ticket use, verify renting/list state, displayed remaining duration, ticket recharge DOM, direct reload behavior, and the separate no-click Premium Ticket UI at `320474`.

### M3a retry on a different work (2026-09-22)

The user explicitly authorized one Work Ticket consumption on
`title_id=02585`, episode `401350`, and asked to inspect Premium Ticket UI on
episode `401715`. This is a separate work from the stopped `01367` attempt.

#### Complete episode-list observation

- Work title: `となりの黒川さん`; list total: 57 episodes; expansion: 10 → 57; DOM order newest-to-oldest.
- Before consumption, `401350` was `【第4話】気になります` and
  `401715` was `【第5話】すれ違う想い`. Both rows showed
  `.c-episode-item__ico--ticket-free` with `img alt="無料"`.
- State counts at this observation: 46 `--ticket-free`, 10 `--free`, 1
  `--point`, 0 `--renting`.
- `order_key` remains `None`; no Discovery or Catalog data was changed.

| DOM index | episode_id | Raw title | Access class |
| ---: | ---: | --- | --- |
| 0 | 443848 | 【第52話】熱あるんじゃないか | `--point` |
| 1 | 443119 | 【第51話】すけこましめ | `--free` |
| 2 | 442060 | 【第50話】ずるい… | `--free` |
| 3 | 441310 | 【第49話】すれ違いとすり合わせ | `--free` |
| 4 | 440715 | 【第48話】んもう！ | `--ticket-free` |
| 5 | 440019 | 【第47話】返せぇぇぇ!! | `--ticket-free` |
| 6 | 439142 | 【第46話】とにかく暑い日 | `--ticket-free` |
| 7 | 438372 | 【第45話】これはデートです | `--ticket-free` |
| 8 | 437937 | 【第44話】そんなヒマはない！ | `--ticket-free` |
| 9 | 436397 | 【第43話】それぞれが抱く気持ち | `--ticket-free` |
| 10 | 436396 | 【単行本4巻発売記念おまけ】「走る!! 弥生ちゃん！」 | `--free` |
| 11 | 435011 | 【第42話】意識しすぎて… | `--ticket-free` |
| 12 | 434398 | 【第41話】勇気を出して | `--ticket-free` |
| 13 | 432600 | 【第40話】見える… | `--ticket-free` |
| 14 | 432064 | 【第39話】どうしたら… | `--ticket-free` |
| 15 | 431411 | 【第38話】冷静ではもちろんいられない | `--ticket-free` |
| 16 | 430750 | 【第37話】高橋の父について | `--ticket-free` |
| 17 | 430125 | 【第36話】そういうところが | `--ticket-free` |
| 18 | 429464 | 【第35話】恋の相談？ | `--ticket-free` |
| 19 | 428688 | 【第34話】どうしよう。 | `--ticket-free` |
| 20 | 428494 | 【単行本発売記念おまけ】「弥生ちゃんの看病…？」 | `--free` |
| 21 | 427861 | 【第33話】責任重大な約束 | `--ticket-free` |
| 22 | 427148 | 【第32話】失いたくないもの | `--ticket-free` |
| 23 | 426440 | 【第31話】努力と不穏… | `--ticket-free` |
| 24 | 425556 | 【第30話】どんな男の子だって | `--ticket-free` |
| 25 | 424822 | 【第29話】2人の約束と勝負 | `--ticket-free` |
| 26 | 424193 | 【第28話】ついに来てしまった | `--ticket-free` |
| 27 | 423466 | 【第27話】気づいてしまったコト | `--ticket-free` |
| 28 | 421653 | 【番外編】玄内さんと弥生ちゃん inイギリス | `--ticket-free` |
| 29 | 420880 | 【第26話】わからせてあげますから | `--ticket-free` |
| 30 | 419995 | 【第25話】黒川さんだけには | `--ticket-free` |
| 31 | 419233 | 【第24話】待ちわびた日 | `--ticket-free` |
| 32 | 418526 | 【第23話】ドキドキソワソワ！ | `--ticket-free` |
| 33 | 417404 | 【第22話】黒川さんの間違い | `--ticket-free` |
| 34 | 416633 | 【第21話】最大の間違い | `--ticket-free` |
| 35 | 415788 | 【第20話】お願いがあるの | `--ticket-free` |
| 36 | 415882 | 【単行本宣伝話】 | `--free` |
| 37 | 415177 | 【第19話】○○を潰す | `--ticket-free` |
| 38 | 413699 | 【第18話】何かのご縁… | `--ticket-free` |
| 39 | 412867 | 【第17話】"ただの散歩"…？ | `--ticket-free` |
| 40 | 412030 | 【第16話】とても | `--ticket-free` |
| 41 | 411432 | 【第15話】確実なので… | `--ticket-free` |
| 42 | 411171 | 【単行本宣伝話】【1巻が発売になりました！】 | `--free` |
| 43 | 408612 | 【第14話】黒川さんの過去 | `--ticket-free` |
| 44 | 407824 | 【第13話】後悔と思い出 | `--ticket-free` |
| 45 | 407134 | 【第12話】兄と妹 | `--ticket-free` |
| 46 | 406561 | 【第11話】ドキドキなお出かけ！ | `--ticket-free` |
| 47 | 405785 | 【第10話】2人のお出かけ！ | `--ticket-free` |
| 48 | 404370 | 【第9話】それって、デ… | `--ticket-free` |
| 49 | 403764 | 【第8話】放課後の危機② | `--ticket-free` |
| 50 | 403155 | 【第7話】放課後の危機① | `--ticket-free` |
| 51 | 402277 | 【第6話】交換したい | `--ticket-free` |
| 52 | 401715 | 【第5話】すれ違う想い | `--ticket-free` |
| 53 | 401350 | 【第4話】気になります | `--ticket-free` |
| 54 | 400199 | 【第3話】エッチじゃ、ないです！ | `--free` |
| 55 | 399935 | 【第2話】彼女は友達 | `--free` |
| 56 | 399934 | 【第1話】彼女はヒロイン？ | `--free` |

#### Work Ticket use and rental observation

- Immediately before use, the shared header showed point `35` and ticket `8`.
  The episode page also said `チャージ完了！`.
- `401350` was `--ticket-free`, not `--renting`. The one visible access
  control was an `<a href="javascript:void(0);">` with exact text
  `作品チケットで読む` and class
  `c-btn-icon-primary c-btn-icon-primary--ticket`. No Premium Ticket or
  point-purchase control was mixed into this access choice. The exact link was
  clicked **once**.
- The viewer appeared on the same URL. Directly reloading
  `.../episode/401350` also opened the viewer without another access click.
- After reload, row `401350` showed
  `.c-episode-item__ico--renting`, `alt="レンタル中"`, and `あと71時間`.
  No absolute expiry timestamp was found in the observed UI.
- Work-level charge DOM changed from `チャージ完了！` to
  `.p-episode__charge-txt` = `あと22時間58分` (observed shortly after
  use); its parent is `.p-episode__charge-meter`. This is a displayed
  countdown, not an absolute recharge timestamp.
- Header counters remained point `35`, ticket `8` after the Work Ticket action.
  No Premium Ticket action was clicked.

#### Premium Ticket UI on episode 401715 (no click)

- Current episode title: `【第5話】すれ違う想い`. The purchase panel was
  `.p-episode-purchase > .p-episode-purchase__inner`.
- The Premium Ticket control was one visible enabled anchor:
  exact text `プレミアムチケットで読む`, class
  `c-btn-icon-primary c-btn-icon-primary--premium-ticket`, href
  `javascript:void(0);`. It is clearly distinct from the Work Ticket anchor
  by both exact label and class suffix. It was **not clicked**.
- The same panel had `dt.p-episode__...`-style label/value content in the
  observed structure: `dl.p-episode-purchase__point` contains
  `dt.p-episode-purchase__point-ttl` = `プレミアムチケット` and
  `dd.p-episode-purchase__point-data` = `8枚`. The reliable count selector
  candidate is scoped to
  `.p-episode-purchase__point:has(.p-episode-purchase__point-ttl)` and reads
  the matching `.p-episode-purchase__point-data`; validate the label text
  before parsing. The header candidate is
  `.l-header__status-item-inner--ticket` = `8`, but is less semantically
  specific by itself.
- Premium Ticket count: before Work Ticket `8` from the header; after Work
  Ticket `8` in the header and explicitly `8枚` in the Premium Ticket panel.
  This supports `premium_ticket_count=8`; the count did not change.
- No Premium Ticket expiry text or expiry bucket was visible in the header or
  purchase panel. No My Page fallback was needed for count retrieval.
- The requested Premium Ticket control was displayed and enabled, but never
  clicked. No point purchase, subscription, or other paid action occurred.

#### Updated provisional M3 recommendations

- A unique Work Ticket action can be recognized as the exact visible link
  `作品チケットで読む` with class
  `.c-btn-icon-primary--ticket`; it is an anchor, not a `<button>`.
- A unique Premium Ticket action can be recognized separately as the exact
  visible link `プレミアムチケットで読む` with class
  `.c-btn-icon-primary--premium-ticket`. Production should fail closed unless
  the requested resource's exact control is uniquely present and does not
  match the other resource class.
- `--renting` → direct entry is now live-confirmed for this work, with no
  second click after reload. Keep `consumes_quota=False`; use the human-readable
  rental/charge countdown only as an observation, not as an absolute expiry.
- Work Ticket availability/charge appears per work: `チャージ完了！` before
  use and `.p-episode__charge-txt` countdown afterward. Prefer observing this
  DOM state over a hard-coded charge duration.
- `--ticket-free` in the list did not itself reveal the final reader-entry
  control: on `401715`, the list class was `--ticket-free` while the page's
  access panel exposed the Premium Ticket option. Future execution must
  inspect the live episode access panel and must not infer Work-vs-Premium
  control solely from the list class.
- `order_key=None` remains unchanged. The observed newest-to-oldest DOM order
  supports reversing a preserved same-work discovery order as a candidate
  oldest-first Batch priority, but not a site eligibility rule.

## M3b active-rental Discovery and Batch support (2026-09-22)

The quota behavior below describes the M3b implementation at that stage. M3c1
later changed expired/no-grant quota sources into Work Ticket candidates.

### Current behavior

- `DiscoveredSource.access_granted_until` carries an optional observed grant
  timestamp through Discovery Service into the existing Catalog column. New
  sources persist a non-NULL observation while leaving `quota_started_at`
  NULL. On refresh, a non-NULL observation updates the grant; NULL preserves
  any stored grant. No schema migration was added.
- For a row whose access icon includes
  `.c-episode-item__ico--renting`, Discovery reads
  `.c-episode-item__txt--renting`, falling back to that row's
  `.c-episode-item__label02-txt`. Only the complete text `あとNN時間` is
  accepted. `あと22時間58分`, missing text, and other formats yield no grant.
  Parsing requires a timezone-aware observation time and returns that time
  plus the displayed whole hours. This is a conservative lower bound, not an
  exact expiry; no extra hour is added.
- `MagapokeSitePolicy` validates grant timestamps. A future grant on a
  `quota` source yields eligible `direct`, `reason="active_rental"`, and
  `consumes_quota=False`. Missing or expired grants remain skipped as
  `quota_not_supported`; invalid/naive timestamps raise `SitePolicyError`.
  Other access states are unchanged. `quota_available` is ignored; no ticket
  capacity, ticket click, schema, Adapter quota entry, Planner, or Executor
  behavior was added.
- Magapoke `order_key` remains `None`. No order key is derived from row
  position. Episode-list ordering and any future oldest-first Batch priority
  remain separate concerns.

### Verification

- Unit tests cover whole-hour parsing, malformed display text, aware-time
  enforcement, Catalog creation/update/NULL-preservation, active/expired grant
  policy, and the existing direct Executor regression.
- Live verification succeeded on 2026-09-22 after restarting shared Crawler
  Chrome. A temporary Watchlist and Catalog were used for
  `title_id=02585`, episode `401350`; full Discovery completed successfully
  with 57 rows (`complete=true`, `stopped_reason=exhausted`). The observed
  source had `access_mode=quota`, a future JST `access_granted_until`, and
  `quota_started_at=NULL`. This confirms the current row countdown parsed to
  the conservative lower bound and persisted without a schema change.
- The real `batch plan --site magapoke` CLI exited successfully against that
  temporary Catalog: 11 eligible/direct candidates, 0 quota candidates, and
  46 skipped. Episode `401350` was candidate source 54 with
  `access_mode=quota`, `access_strategy=direct`, `reason=active_rental`, and
  `consumes_quota=false`. The temporary plan recorded zero CrawlRuns and zero
  Artifacts. The temporary Watchlist and Catalog were removed on completion.
- No viewer access control was clicked, and no Work Ticket, Premium Ticket,
  point, subscription, or other resource was consumed. The first retry before
  restarting Chrome had hit the earlier 180-second CDP handshake timeout; the
  successful retry confirms that restart resolved the connection problem.
- Premium Ticket behavior and all M3c consumption remain out of scope.

### Phase 3 generic access-resource contract

Phase 3現在、Magapoke Policyはgeneric access-resource contractとして
`work_ticket` -> `premium_ticket`のsupported/orderを提供する。Batchは通常pass後に
Catalogをreplanして追加resource passを実行し、requested resourceと異なるresourceへの
silent fallbackをしない。grant-only、Work Ticket cooldown persistence、resource stateの
永続化はPhase 4で実装済みで、Premium/allはPhase 5で実装済みである。

### Phase 4 grant-only current state

Magapoke supports generic grant-only for `work_ticket`; Phase 5 additionally
supports `premium_ticket`. The normal adapter
entry path is reused with Core entry-only execution, so no content capture,
packaging, or Item completion occurs. Confirmed consumption is stored atomically
as source grant plus Catalog schema v5 `quota_resource_states(work_id, site,
resource, last_consumed_at)`. The default local negative cooldown is 23 hours;
state skips happen before site access and exactly-expired state is live-checked.
Premium consumption is source-grant-only; Premium balance is live-only and does
not create a `quota_resource_states` row. `--grant-only all` is the Policy-ordered
Work Ticket then Premium Ticket orchestration and replans Catalog between passes.
Normal Batch uses the same observed Work Ticket persistence path as grant-only;
confirmed consumption is retained if a later crawl or finalization step fails.
This current-state section supersedes the older Phase 3 planning sentence.

### Phase 5 current state: Premium Ticket grant-only and all

Premium grant-only reads the exact live semantic balance immediately before the
Premium control. A clear zero produces `premium_ticket_exhausted`, closes the
candidate, and stops the Premium pass without opening later Premium candidates.
The normal UI's Work Ticket priority is respected: a Work-only or mixed/unknown
access panel never forces Premium or another purchase control. Confirmed
Premium consumption uses `policy.access_grant_until(consumed_at)` (the current
conservative 71-hour grant) and leaves the Item pending. Later failure retains
the source grant through the shared observed-consumption helper. `all` obtains
its order from Policy, replans after each pass, shares one total site-attempt
limit, and preserves inter-candidate pacing. Premium balance is never cached or
persisted in Catalog. Phase 6 automated cross-site regression is verified, but
live verification is partial. The full automated suite covers Work and
Premium persistence, `all` replanning, zero-balance pass stop, normal capture,
and shared pacing/AccessGuard behavior. New normal live Batch and Ticket
consumption were intentionally not forced; details are in
`docs/PHASE6_VERIFICATION.md`.

### Entry confirmation and failure diagnostics current state

Work/Premium Ticket confirmation requires the requested control to disappear
and usable viewer content to be observed. Content evidence may be native
canvas rows or a visible non-empty viewer canvas. This fallback is limited to
entry confirmation; native capture still requires its existing canvas-source
state. Resource mismatch, ambiguous controls, or a still-visible requested
control fail closed, and Ticket resources never silently fallback to each
other.

Failure diagnostics include body-free Magapoke entry signals such as canvas
row count, visible canvas count, requested resource, Ticket-control visibility,
and capture-hook presence. Ticket confirmation additionally retains a bounded
poll trace with probe timing, canvas/viewer observations, Ticket-control state,
and probe errors. Ticket-control observation uses one atomic DOM snapshot so a
same-document reload does not consume the whole confirmation window through
sequential Locator waits; a transient Playwright/DOM probe error is recorded
and retried within the remaining bounded window. If viewer content is already
accessible before the requested Ticket click, the state is recorded as
preexisting access and does not create a
grant or resource-consumption record. Missing confirmed consumption in
entry-only execution is reported as `AccessConsumptionUnconfirmedError`.
Candidate site-operation failures stop the Batch after the current candidate
cleanup, while cooldown/resource-unavailable outcomes remain skips. Operator cancellation records
`interrupted`, preserves only confirmed consumption, and prevents later
candidates from starting.

Grant-only uses Magapoke's `initialize_entry_only()` path. It performs the
viewer/access entry and confirmed-consumption checks, then returns without
native canvas-row rewind or full render stabilization. A visible viewer canvas
can therefore complete grant-only confirmation even when native canvas rows
remain empty; normal crawl capture and navigation keep their existing native
row requirements. AccessGuard and browser/page cleanup are bounded, and an
initialization error remains the primary failure if cancellation occurs during
cleanup.

### Phase 1 runtime pacing / Batch ordering

Magapoke Discoveryの列挙順は引き続きlatest-firstであり、Discoveryのreverseは行わない。Batchは既存のdirect先行・
Work間stable orderingを維持し、同一Workの各Batch phase内を`published_at ASC (NULL last), source_id DESC`で
old-to-newに並べる。root `crawler.yaml`の`page_turn_delay_ms`はCONTENTの全artifactとprogress persist後、
initial `go_next()`直前に1回だけ適用する。Batchの`inter_candidate_delay_ms`はcandidate Page close後、次の
site-accessing candidate前に1回だけ適用する。Magapoke adapterのnavigation retry、Work Ticket、Premium Ticket、
direct accessの既存挙動は変更していない。Phase 2ではMagapoke adapterがshared AccessGuardへ接続され、
`pocket.shonenmagazine.com`と`mgpk-cdn.magazinepocket.com`のrelevant hostだけの403/429をfatal stopとする。
explicit challengeとvisible CAPTCHAも共通stop reason/Batch JSONL metricsへ記録する。
site-specific signalのlive verificationは未実施である。Phase 6のcross-site
自動回帰は完了し、実サイト確認は一部未実施である。詳細は
`docs/PHASE6_VERIFICATION.md`を参照する。
