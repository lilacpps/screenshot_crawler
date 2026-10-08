# Stage 02 checkpoint — 2026-10-08

Status: **INCOMPLETE / ACCESS PRECHECK BLOCKED**. Authority is [README.md](README.md).

This checkpoint preserves the useful evidence from the earlier heavier workflow while
making clear that Reviewer/Critic are no longer required for ordinary research.

## Baseline synchronization completed (not research evidence)

- Continued on `research/bookwalker-source-native-20261005` in the existing worktree.
- Initial local HEAD: `0209a8791a3d2bc7b11b0bff8018a7c039a24b8c`.
- Fetched `origin`; current `origin/main` was
  `96fd5fff84567a4e2c644978d2b4c297174fa2ca`.
- Merged that main baseline, then preserved the remote research branch's preflight
  documentation through `7d199d6`. Resulting baseline HEAD:
  `ef956698f92d30441a71be785b6bb5ac874011a5`.
- Both merges completed without conflicts. Stage 02 README/checkpoint and the
  BookWalker note remained present. Main's packaging/status documentation was
  retained; no BookWalker production Python change arrived through these merges.
- The unrelated untracked `debug.log` was left untouched; its before/after SHA-256
  was `13195f4a9302dee588b1705b9d691d4d1999b91505cfecedc70196edbc3db489`.

These SHAs record this execution, not a pinned main requirement for a future run.

## 2026-10-08 access-only precheck

The Lead selected one fresh manga question: can the selected ordinary-body bitmap
at `9/159` be attributed one-to-one to an exact upstream encoded source? The
Worker could not reach that anchor. No fresh source/geometry/pixel probe ran.

- Initial manga `direct` entry reached a login form; an `auto` attempt also failed
  to reach a ready viewer. A quota control lookup found no matching maruyomi
  control and did not click a resource control. These attempts are access
  observations only, not provenance probes or a supported fallback strategy.
- Configured email/password presence was true. The existing login-form helper
  submitted once in a dedicated new Page, observed a viewer destination and
  disappearing login form, then closed only that Page. No credential value,
  Cookie, storage state, or signed viewer URL is recorded here.
  An initial helper invocation could not find the home-page login button and
  submitted no form; the subsequent visible member-form submission was the
  single actual login submission.
- After login, manga strict-direct control kinds were `trial`, `unknown`, and
  `generic_reader`; no `owned` control was available, so no direct click ran.
- The independent LN strict-direct precheck observed `generic_reader`, `maruyomi`,
  `subscription`, and `unknown`; no `owned` control was available and no direct
  click ran. There was no quota/auto/trial switch for LN.
- No quota control was clicked and no resource consumption was reported. The
  cause of missing owned controls and the current account's entitlement are not
  proven by these observations.
- Actual reader counters, start/end positions, and anchor restoration were
  unavailable for both targets. No fresh `1/159`, `9/159`, `1/314`, `2/314`, or
  `3/314` position is claimed.
- The Lead requested that the user make the intended account available in the
  shared Crawler Chrome. Live operations then stopped to avoid competing with
  manual login. No new viewer/probe helper, fixture, or production code was added.

The Worker confirmed the CDP endpoint at `http://127.0.0.1:9222` and the Chrome
process's repository `.chrome-crawler` profile. Each access attempt used and
closed a dedicated Page; remote Chrome remained running. The metadata-only local
report `output/stage02-access-precheck-20261008.json` has SHA-256
`cc0507be54346bed35b108eef08a3614ffd57ac38a4e71f33128b575b0547997`.
It records the seven entry/login attempts without image bytes or secrets. Its
structural observations are summarized above so the ignored local report is
not required to understand this checkpoint.

Stage 02 is **not complete**. Access failure does not establish D. Current
classification remains the historical evidence below:

| Case | Retained classification | Still missing |
| --- | --- | --- |
| Manga cover | A (historical) | No fresh regression claim |
| Manga ordinary body | D | Exact encoded JPEG/PNG attribution and complete source/output proof |
| LN `2/314` | D | Exact selected-output lineage from the all-pixel-matched 1448x2048 JPEG/bitmap |
| LN `3/314` | D | Exact selected-output lineage, crop/padding/coded mapping and complete visible-output proof |

Manga 2 remains unused: no new renderer/provenance pattern was obtained that
requires a cross-title test. Research has paused for target access, not because
additional provenance research was judged unproductive.

## Checks and cleanup in this continuation

- PASS: `.codex/config.toml` parses with `tomllib`; spawned-thread limit is 2.
- PASS: `.venv/Scripts/ruff.exe check src tests`.
- PASS: `git diff --check` after the merges and documentation/cleanup changes.
- Production Unit/Integration/full pytest were not rerun: this continuation
  changed documentation and the research thread cap only, with no production or
  durable diagnostic/test contract change. No pytest skips occurred because
  pytest was not invoked. Fresh provenance Live verification remains unexecuted;
  only the access checks above ran. Old Stage 01 test counts are historical.
- Restored `max_concurrent_threads_per_session = 2`; no reason remains to retain 4.
- Replaced the BookWalker note's universal PNG-saving scope, dedupe and packaging
  wording with the current original/reconstructed JPEG, source/native PNG and
  rendered fallback behavior.
- Reviewer/Critic were not invoked: no production change, proof-gate change,
  heuristic attribution, or broader generalization was proposed.

## Immediate next action

After the intended account can open the targets in the shared Crawler Chrome,
Worker must recheck actual counters and strict access. Do not assume the login
Page's viewer destination was either research target. Resume the single
`9/159` manga spread question first; classify its evidence before deciding on a
second spread. Then probe LN `2/314`, inspect the result, and only then select
the bounded `3/314` question. Do not rerun credentials or choose another resource
merely to bypass the missing owned control.

## Accepted current evidence

- Production capture code remains unchanged.
- Stage 01 cover A and ordinary LN-text A evidence remain historical controls.
- Manga ordinary body remains D.
- LN opening remains D.
- Manga 2 has not been used.

Latest live manga R5:

- actual initial position was `9/159`;
- Worker rewound and verified `1/159`;
- captured `1/159`, `3/159`, `5/159`, `7/159`, `9/159`;
- ended at `9/159`;
- restored and verified `1/159`;
- at `9/159`, two selected native PNG artifacts were 844x1200;
- selected lineage had two 1,026-tile mappings with 38 destination-edge clips each;
- exact encoded-source attribution was not proven;
- inventory contained only 158x224 JPEG thumbnails among eligible observed JPEGs.

R5 establishes bounded native lineage, not source-PNG authority or reconstructable JPEG
proof.

Its first capture used rendered fallback and is not a fresh cover-A regression pass.

## Previous diagnostic work

OBJECT-A and related local diagnostic files were developed under the previous workflow.

They were not fully reviewed and are **not production/source-format authority**.

They may be:

- reused if Lead decides they directly answer a concrete bounded question;
- ignored or retired if a simpler direct probe is more efficient.

There is no requirement to finish OBJECT-B/C or a synthetic producer matrix.

The earlier agent-thread-capacity problem no longer blocks research because normal
research now uses only Lead + Worker.

## Resume order

1. Continue on `research/bookwalker-source-native-20261005`; do not create a replacement
   branch just because `main` has advanced.
2. Fetch `origin` and merge the current `origin/main` into this branch before new
   live research or production edits. Preserve both newer main behavior and this
   checkpoint/runbook evidence when resolving conflicts.
3. Lead reads this checkpoint and the current Stage 02 README after the merge.
4. Do **not** restore Reviewer/Critic merely to satisfy the old gate sequence.
5. Pick the smallest direct unresolved manga or LN provenance question.
6. Worker performs one bounded probe.
7. Lead classifies the result A/B/C/D or asks one more bounded question.
8. Stop research when another probe is unlikely to change the operational decision.
9. If production code is implemented, invoke Reviewer.
10. Invoke Critic only if a material risk trigger in the README applies.

## Local ignored artifacts

The following hashes identify earlier local files but do not make them repository
authority:

| Local file | SHA-256 |
| --- | --- |
| `output/stage02_manga_provenance_probe.py` | `95a8c17d3801022ba2e797c69d94f1249942edf0a3351073a5e93a2514ccc634` |
| `output/stage02_create_image_bitmap_synthetic_browser_check.py` | `2174c62fb749daf425ffb1aae5ae8aa1d46aa75cf4df59cdec023549d65253af` |
| `output/stage02_create_image_bitmap_observer.py` | `c5aab98c6584b5f6d1c1439d7523503a3322f592500e08218046df1cf64c5517` |
| `output/stage02-manga-ledger/create-image-bitmap-synthetic-evidence.json` | `644d29f3fc885bc0294d699d54067b33cb0da6c397e74332632d96fcc90d2fc7` |

A fresh clone need not reproduce or complete these files unless Lead explicitly chooses
that route.
