# カドコミ Free-Only Adapter — Progress / evidence ledger

Status: **P0/P2 RESEARCH IN PROGRESS; P1.5 SHARED HOOK VERIFIED**
(2026-10-12)。P1 Kadocomi adapter実装は未開始。現在の公開一覧とquery-free episode
input identityは限定確認済み。過去/配信終了分の完全性、no-deadlineのfree判定、original-byte
帰属、reader ENDは未確定。この文書はLeadが更新する。**未検証のことを成功記録にしない。**

## Stage checkpoints

| Stage | 状態 | 根拠/残課題 |
| --- | --- | --- |
| P0 Site/Original research | IN PROGRESS | Exact ULで現在の53/53 entriesをsettle確認し、query-free exact episode inputもidentity照合。expired gaps / no-deadline free / original-byte attribution / ENDは未確定 |
| P1 Discovery | NOT STARTED | list展開、free分類、free_until、full/incremental、履歴を実装 |
| P1.5 Position | SHARED HOOK PASS | 独立Reviewer BLOCKING=0、51 passed / 0 skipped。Kadocomi adapter側での利用と履歴検証はP1実装時 |
| P2 Viewer/Capture | IN PROGRESS | 最初の3 source slotで同寸法full-frame drawを確認。byte/source/page provenance、page order、ENDは未確定 |
| P3 Free-only Batch | NOT STARTED | directだけを既存Planner/Executor/ZIPに統合 |
| P4 Independent E2E | NOT STARTED | fresh Catalog実サイト、独立画像監査、Reviewer BLOCKING=0 |

## Initial user-provided observations (hypotheses, not evidence)

- 作品URL: https://comic-walker.com/detail/KC_004915_S?episodeType=first
- 「全XX話を表示」で話一覧を展開。
- 公開中の話に無料バッジがない場合があり、配信期限がある場合もある。
- 終了した話は「第XX話から第XX話は配信が終了しました」等で表現。
- 単行本や他の導線も混じりうる。
- 配信終了/再公開に伴い、途中話のID・位置・公開状態が変わる可能性がある。

これらの初期メモは仮説として扱う。確度を分けた現行live evidenceとUNKNOWNは以下に記録する。

## P0 live evidence (incomplete; 2026-10-12)

### Environment / containment

- Branch/worktree: `feat/kadocomi-adapter` in the dedicated
  `screenshot_crawler_kadocomi` worktree. The original workspace's dirty
  `crawler.yaml`, `watchlist.yaml`, and `debug.log` were not touched.
- Connected to the already-running shared Crawler Chrome at
  `http://127.0.0.1:9222` using Playwright from the original workspace venv
  (Python 3.14.6). The shared profile's one existing tab was blank.
- All site navigation used an additional fresh anonymous BrowserContext; only
  the probe-owned context was closed. Remote Chrome remained running. The
  anonymous context had no `user` in the site's `/api/auth/session` response;
  the site did set anonymous cookies during navigation.
- No screenshots, response bodies, cookies, tokens, or image files were saved.
  Source-byte signatures were checked in memory only. Local `work/kadocomi/`
  is excluded via this worktree's Git info/exclude; no persistent probe output
  is currently required.
- No production code changed; no test suite was run for this research-only
  checkpoint.

### OBSERVED

- The seed detail page returned HTTP 200 in a fresh anonymous context. Its
  initial UI showed `全53話を表示`, a page-level `無料話増量中` banner/countdown,
  and episode links. The seed URL included `episodeType=first`.
- Clicking the unique expansion control exposed the exact observed list
  container `DIV.EpisodesTabContents_root__VrJZ1 >
  UL.EpisodesTabContents_episodeList__cIDQz`. That UL contained 53 distinct
  episode links, matching the declared 53. Two identity-and-deadline snapshots
  0.5 seconds apart matched. A broader page-anchor query found an extra teaser
  outside the UL; it duplicated a list episode and is excluded from the count.
  The visible sequence includes labels 1 through 26 and then 78/79, with no
  explicit 配信終了 range placeholder observed in this list.
- The `無料話増量中` banner is page-level, not a row badge. 46 of the 53 exact
  list rows had the explicit deadline `2026-10-14 11:00`; the other rows had no
  displayed deadline. Exact target 4.1 (`KC_0049150000400011_E`) is one of the
  deadline rows. No row-specific campaign marker was observed.
- Query-free episode input
  `https://comic-walker.com/detail/KC_004915_S/episodes/KC_0049150000400011_E`
  returned HTTP 200 and rendered the same work/episode H1 in an anonymous
  context. The site then added `?episodeType=first` to the route; episode
  identity remained the requested target. No password field, CAPTCHA, expired
  message, ticket/coin/point/purchase gate, 403, or 429 was observed. A generic
  login button remained in site navigation; it was not used.
- `/api/contents/viewer` returned a 200 response with 21 manuscript entries
  numbered 1..21 for target 4.1. The seed's initial `episodeType=first` view
  separately returned 38 entries, so first-episode preview state and exact
  episode state must be bound to the canonical work/episode path before use.
  The returned viewer object exposed promotion time fields but no explicit
  free/access flag in the inspected top-level schema. A
  `/api/contents/viewer-jump-forward` response described an in-place next
  episode with 11 pages; this was metadata only, and no next transition was
  clicked.
- Target reader DOM had 21 canvas elements and a visible slide-navigation UI.
  An independent bounded renderer inspection observed the first three source
  slots (0, 1, 2) drawn full-frame at 836x1200 with an identity transform.
  Earlier inspection also observed 836x1200 canvas backing dimensions with a
  smaller CSS display size. This does not yet prove exact source-byte
  attribution, all page identities, navigation order, or END.
- Some first-party resource responses observed during the target reader session
  had `.webp` path suffixes and `application/octet-stream` MIME. In-memory
  prefixes did not contain RIFF/WEBP magic and Pillow could not identify them
  as images. Exact draw-source-to-response correlation is unproven. No decode,
  decryption, or transformation was attempted; no bytes were saved. They are
  opaque candidates, not verified original images.

### INFERRED (limited)

- The stable 53/53 UL is the currently observed public episode list, not a
  lifetime episode count. The visible sequence gap and absent end-range text
  leave the reason/count of missing historical positions unknown.
- Compacting the current linked list to 1..53 would assign unsupported
  historical positions. Preserve existing Catalog positions; new/unproven
  positions should remain NULL until a site-wide position authority is proved.
- Official Comic Walker help describes WEB as a free manga portal
  ([service overview](https://help.comic-walker.com/hc/ja/articles/24221086268697));
  the deadline FAQ states deadlines are shown only when configured and a
  no-deadline episode may end without notice
  ([deadline FAQ](https://help.comic-walker.com/hc/ja/articles/24220791385241)).
  Together with exact public-list membership, the row's future deadline, and
  anonymous exact-episode readability, this supports only the observed
  deadline-row target as free. The page-level campaign is not row evidence and
  does not establish free status for rows without deadlines.
- Raw response bodies do not currently support direct original-byte capture.
  A normal-renderer source/draw observation may still establish native pixels;
  opaque bytes alone do not prove that route impossible.

### UNKNOWN / NOT VERIFIED

- Whether another page/pagination contains entries outside this exact UL, and
  why historical labels 27..77 are absent. Two stable snapshots establish the
  current 53-row UL only; a full-list disappearance policy still needs more
  than this one work's observed surface.
- Any exact ended-range row format, semantics for partial episodes, and how a
  range maps to historic source IDs/positions.
- Stable episode IDs across unpublish/republication, episode ordering
  authority, and episode-code-to-display-position mapping. Do not derive
  position from IDs or compact list rank.
- Whether rows without a displayed deadline are free; the bounded anonymous
  no-deadline variant attempt stopped before navigation because row selection
  was not verified, so it produced no target evidence. Treat them as UNKNOWN.
- An explicit public FREE/access field in DOM or official API.
- Whether all original response bytes map to the observed renderer draws, and
  stable first/middle/last page identity, reader navigation order, composition,
  loading behavior, and END. The first three draw observations do not settle
  these facts.
- Whether accessing rendered canvas pixels is an acceptable capture route given
  the opaque original responses. No DRM/access-control bypass is authorized.
- A structurally different work and an explicitly labeled ended-range example.

### Next bounded probes / checkpoint

1. Complete bounded normal-reader identity/order checks through the site's
   ordinary controls and verify last page/END; do not use drag gestures that
   can cross episode boundaries.
2. Correlate normal renderer source objects/currentSrc to exact episode/page
   responses and determine whether original bytes are available without
   bypassing access controls. Keep source pixels/copies out of committed
   evidence.
3. If a fresh anonymous no-deadline target can be safely identified from the
   exact UL, test only that public page and preserve UNKNOWN if no positive
   access evidence appears.
4. P1.5 shared-hook implementation passed independent review;
   P1 Kadocomi Discovery implementation has not started. P2 remains open.

## P1.5 shared position-inference hook (2026-10-12)

- `DiscoveryAdapter.allow_inferred_display_positions` defaults to `True`, so
  existing adapters retain their current behavior.
- Setting it to `False` suppresses only position fallback inference when
  complete global hints are absent: full, exhausted incremental, and
  early-stopped incremental runs leave existing positions unchanged and new
  Sources NULL. Complete validated global hints still apply.
- Incomplete runs still do not finalize positions. The hook does not change
  Catalog schema, missing-source reconciliation, item status, Completed state,
  or Artifact identity.
- Changed scope: shared `DiscoveryAdapter`/`DiscoveryService`, focused unit
  coverage, `docs/DISCOVERY_AND_BATCH.md`, this note, and `note/00_core.md`.
  No Kadocomi Discovery parser or live-site behavior changed in this iteration.
- Root-reported pre-change baseline: `tests/unit/test_discovery.py` — 46 passed,
  0 skipped (9.03s). This is the prior baseline, not validation of this diff.
- Current validation: `tests/unit/test_discovery.py` — 51 passed, 0 skipped
  (10.88s); Ruff on `base.py`, `service.py`, and `test_discovery.py` — passed.
- No live-site work was performed in this iteration. Independent Reviewer
  verified the exact final diff: BLOCKING=0, outstanding NON-BLOCKING=0,
  independent targeted validation 51 passed / 0 skipped, diff check clean.
  Lead accepts this shared-hook checkpoint and advances to P1 implementation.
  Site-local history/republication fixtures remain required for the P1 gate.

## Checkpoint template (phase完了時に追記)

```text
Phase:
Branch / commit / date:
Scope and evidence:
  OBSERVED:
  INFERRED:
  UNKNOWN / NOT VERIFIED:
Changed paths:
Test results (commands, PASS/FAIL/SKIP):
Live browser / source image audit:
Reviewer findings (BLOCKING/NON-BLOCKING/VERIFIED):
Decisions and tradeoffs:
Remaining risks / next step:
```

Local実サイト証拠は`work/kadocomi/`等の隔離・gitignored領域へ。
cookie、session token、署名付きURL、実画像そのもの、機密metadataはcommitしない。
