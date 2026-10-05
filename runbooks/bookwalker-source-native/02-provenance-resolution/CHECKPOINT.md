# Stage 02 checkpoint — 2026-10-06

Status: **INCOMPLETE / REQUIRED REVIEW BLOCKED**. Authority remains [README.md](README.md).
This checkpoint documents partial research; it does not approve production changes
or replace Reviewer/Critic gates.

## Current scope and evidence

- Production capture code is unchanged. Original-JPEG priority, existing proven
  reconstruction, and safe native/rendered fallback remain unchanged.
- Entry Critic was performed. Manga body and LN opening attribution challenges
  remain unresolved; no new B or C classification has been approved.
- Stage 01 cover A and LN ordinary-text A observations remain historical baseline
  evidence, not fresh Stage 02 regression results.
- The optional second manga was not used: there is no concrete cross-title
  generalization question yet.

The latest actual live probe is manga R5, using the normal Core capture lifecycle.
It read actual initial `9/159`, explicitly rewound and verified `1/159`, captured
`1/159`, `3/159`, `5/159`, `7/159`, `9/159` with before/after counter checks, ended
at `9/159`, and verified restoration to `1/159`. At `9/159`, two selected native
PNG artifacts were 844x1200. Exact selected renderer/canvas/mapping identities
and operation ordering led to two 1,026-tile mappings, with 38 destination-edge
clips each. This establishes bounded native lineage, not full tile coverage,
encoded producer attribution, source-PNG authority, or DCT/qtable reconstruction.
The candidate pool contained no eligible full-resolution source; the inventory
contained only 158x224 JPEG thumbnails. Nearby JPEGs were not attributed by
dimensions, timing, names, or visual similarity.

R5's first capture used rendered fallback (878x621), so it is **not** a fresh
cover-A regression pass. No live run after R5 and no Stage 02 LN live probe has
completed. Manga ordinary-body and LN opening baseline D remain fail-closed;
a diagnostic-method defect must not be relabeled as site/source D evidence.

## Diagnostic gate and local artifacts

Earlier scoped Reviewer gates accepted foundation/native-brand/ownership,
strict rows, and envelope/counter controls. They did not approve the entire
producer capability or classify any real-site source.

The latest OBJECT-A repair is **Worker-reported only**, awaiting actual Reviewer:
same-ticket identity across collector stages, a passing two-part control,
four isolated reference-mutation controls, measured pixel/byte equality,
source-reference mutation during Blob-read await, and primary-exception identity
after cleanup. Required review must verify those claims and explicit unavailable/
unbound outcomes for both parts, not infer coverage from an aggregate check count.

Current local SHA-256 values, independently checked as file identities:

| Local file (ignored, not included in this commit) | SHA-256 |
| --- | --- |
| `output/stage02_manga_provenance_probe.py` | `95a8c17d3801022ba2e797c69d94f1249942edf0a3351073a5e93a2514ccc634` |
| `output/stage02_create_image_bitmap_synthetic_browser_check.py` | `2174c62fb749daf425ffb1aae5ae8aa1d46aa75cf4df59cdec023549d65253af` |
| `output/stage02_create_image_bitmap_observer.py` | `c5aab98c6584b5f6d1c1439d7523503a3322f592500e08218046df1cf64c5517` |
| `output/stage02-manga-ledger/create-image-bitmap-synthetic-evidence.json` | `644d29f3fc885bc0294d699d54067b33cb0da6c397e74332632d96fcc90d2fc7` |

Worker reported synthetic Chromium 231 checks / zero failures, self-test at
counters 9 and 21, compile, and Ruff passes. These are not accepted gate results;
no skip count is inferred. A fresh clone does not contain these local files.
Preserve the original workspace or reproduce/review the diagnostic work before
relying on it. No BookWalker page bodies, credentials, or storage state are
included in this checkpoint.

## Blocker and resume order

The same required Reviewer could not be restored twice (`agent thread limit reached`),
including a retry after Worker completion. No new agent was created. This session
exposes no close/archive/delete-thread operation; completed status does not prove
capacity is released. The previously approved config limit change from 2 to 4
did not resolve this observed blocker. No further increase or private bypass is
authorized by this checkpoint.

After supported client/runtime capacity recovery:

1. Restore the required actual Reviewer and review OBJECT-A. Previous blockers
   remain uncleared until that review; do not resume live or production work first.
2. Lead has frozen further producer-capability development. Have the actual Critic
   assess a narrow safe-no-change exit using accepted R5 facts and explicit missing
   encoded-source proof, versus the concrete value of further diagnostic work.
3. Do not mechanically finish OBJECT-B/C, wrapper-produced PNG-pair integration,
   or the remaining producer matrix merely to complete a framework. If the
   capability is retired, exclude its unreviewed output from evidence; unused
   capability tests need not be completed. This does not waive site evidence.
4. Complete necessary manga later-spread/LN `2/314` and `3/314` probes, bounded
   cover/body/text regression controls, required tests, note synchronization,
   and final Reviewer/Critic gates under Lead decisions and the README criteria.

This publishing change is documentation plus the already-approved agent config
checkpoint only. It does not claim Stage 02 completion, new source-native output,
fresh production tests, or final live regression success. The original watchlist,
unknown `debug.log`, and ignored diagnostic files are excluded and preserved.
