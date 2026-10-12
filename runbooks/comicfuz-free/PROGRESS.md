# ComicFUZ Free-Only Adapter — Progress and Evidence

Updated: 2026-10-12
Branch: `feat/comicfuz-adapter`
Seed: https://comic-fuz.com/manga/1970?position=thumbnail
Site key: `comicfuz`

**Current status: PLANNED.** This commit adds the execution runbook only. There is **no completed site probe, implementation, test, live Batch or validated access/capture claim**.

| Phase | Status | Evidence / exit condition |
| --- | --- | --- |
| 01 — Site probe | NOT STARTED | Anonymous list/identity/access, free target(s), viewer, image provenance and END observed |
| 02 — Discovery | NOT STARTED | Full/incremental and any verified bounded path; Catalog identities/order/completeness reviewed |
| 03 — Viewer/Capture | NOT STARTED | Verified anonymous free entry, all pages and END; capture evidence and reviewer |
| 04 — Batch | NOT STARTED | Direct-only policy, CLI integration and normal Planner→ZIP→Completed |
| 05 — Independent E2E | NOT STARTED | Isolated live run, page/ZIP/Catalog audit, reviewer BLOCKING 0 |

## Facts and deferred questions

- **USER REQUIREMENT:** initial v1 covers anonymous public-free episodes; user is currently logged out; charge/ticket/medal discovery and processing are explicitly **deferred to a next step**, not a v1 gate.
- **USER-SUPPLIED SEED:** `https://comic-fuz.com/manga/1970?position=thumbnail`. Its canonical identity, public listing completeness, current public-free rows and viewer structure have **not yet been live-verified by this work**.
- **REPOSITORY FACT:** existing site adapters include Zeblack, Manga ONE, Comic DAYS and free-only policies; reuse is to be decided by evidence.
- **HYPOTHESES, NOT FACTS:** ComicFUZ may have a protocol or viewer similar to one of these sites. Protobuf/encoding/tiling/original-byte retrieval/END remain **UNKNOWN**.
- **DEFERRED:** authenticated charge recovery, remaining balance, tickets, Silver/Gold medals, consumption UI, active grants and expiries.

## Checkpoint template (append as phases advance)

### YYYY-MM-DD — Phase XX — status
- Branch/head SHA / changes / note sync:
- Observed facts (site URL and local timestamp, content identity, anonymized safe artifacts):
- Hypotheses / unknowns:
- Allowed/changed files:
- Tests executed and results (including skip counts and unrun categories):
- Live page sequence / END / source/native-fidelity proof where applicable:
- Catalog, Manifest/ZIP/CRC and output audit:
- Reviewer: BLOCKING / NON-BLOCKING / VERIFIED:
- Lead decision / next phase / external blockers:

Never record credentials, session tokens, request headers, signed URLs or comic image contents. Keep historical attempts but clearly distinguish current production behavior and observations from hypotheses and old failures.
