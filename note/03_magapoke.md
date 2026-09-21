# 03. Magapoke

## Purpose and scope

`MagapokeAdapter` crawls one episode through the shared Crawler Chrome/CDP
session. Magapoke Discovery is implemented separately for episode-list
enumeration and Catalog synchronization. Batch, SitePolicy, login, purchase,
quota operations, active-grant persistence, and ticket consumption remain out
of scope.

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
arrival order. The next operation clicks `.c-viewer__pager-next` once and
bounded `wait_for_change()` waits for either identity or URL change. A URL
change from episode 244815 to 244816 is a normal `NEXT_CONTENT` completion and
244816 is not captured.

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
