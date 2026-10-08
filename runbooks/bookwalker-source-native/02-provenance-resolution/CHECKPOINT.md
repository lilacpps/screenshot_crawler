# Stage 02 checkpoint — 2026-10-06

Status: **INCOMPLETE / WORKFLOW REVISED**. Authority is [README.md](README.md).

This checkpoint preserves the useful evidence from the earlier heavier workflow while
making clear that Reviewer/Critic are no longer required for ordinary research.

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
