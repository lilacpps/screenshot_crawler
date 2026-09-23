# Magapoke Access / Batch Plan (planned, not yet implemented)

Status: **PLANNED / NOT YET IMPLEMENTED**.

Authority: `docs/MAGAPOKE_BATCH_ACCESS.md`.

This note exists to satisfy note synchronization for the adopted Magapoke Batch/ticket/load-control specification without rewriting `note/03_magapoke.md` as though the behavior were already implemented. `note/03_magapoke.md` remains the current-implementation snapshot until each phase lands; implementations must update that current-state note in the same change.

The latest plan also introduces a small **shared runtime pacing mechanism** used by Magapoke, Manga ONE, and BookWalker. The pacing mechanism is common; ticket/resource behavior below remains Magapoke-specific.

Planned changes:

- keep Batch sequential; do not add configurable concurrency,
- add root `crawler.yaml` as a simple runtime configuration file,
- make these settings generic per-site pacing settings for Magapoke, Manga ONE, and BookWalker:
  - `page_turn_delay_ms: 1000`,
  - `inter_candidate_delay_ms: 3000`,
- keep `work_ticket_cooldown_hours: 23` Magapoke-specific,
- keep safe non-zero code defaults when `crawler.yaml` or a known site entry is absent,
- do not add YAML inheritance/rule DSL behavior in the first implementation,
- pass page-turn pacing into Core through resolved run settings / `RunConfig`; Core must not parse YAML or branch on site name,
- apply page-turn pacing exactly once after a successful CONTENT capture/save and before the initial `adapter.go_next()`,
- do **not** apply that pacing to AD advancement, loading/change polling, same-content waits, ticket entry, or adapter-internal advance retries,
- keep the pacing delay outside the `go_next` / `wait_for_change` timeout budget,
- preserve the existing Magapoke, Manga ONE, and BookWalker adapter-owned retry algorithms; pacing must not create duplicate initial page advances,
- apply `inter_candidate_delay_ms` once between site-accessing Batch candidates, not for local-only skips,
- use deterministic pacing for load control; do not add random/human-like timing or synthetic mouse/scroll/keyboard activity,
- keep Magapoke Discovery latest-first,
- order Magapoke Batch candidates within a Work by `published_at ASC` (NULL last), then `source_id ASC`,
- add `batch run --site magapoke --grant-only work_ticket|premium_ticket|all`,
- grant-only confirms viewer access and persists the grant without capture/package/item completion,
- persist Work-scoped Work Ticket `last_consumed_at` separately from episode/Premium usage,
- if Work Ticket cooldown is <23h, skip that Work locally without site access,
- after cooldown, live UI remains authoritative; unavailable Work Ticket is an expected skip and does not reset the cooldown timestamp,
- respect Magapoke UI priority: when Work Ticket is available, do not attempt to bypass it to force Premium Ticket,
- `premium_ticket` mode skips candidates whose normal UI requires Work Ticket,
- `all` uses Work Ticket when available and Premium Ticket otherwise,
- retain live Premium Ticket balance checks and stop Premium attempts at zero,
- add relevant-host Magapoke HTTP 403/429 fail-safe stop behavior,
- also stop on explicit challenge detection such as `cf-mitigated: challenge`; record a distinct `challenge_detected` style reason and do not auto-retry/solve/reload through it,
- do not add broad DOM/title challenge guesses to Core; explicit response markers or separately live-verified site states are preferred,
- add lightweight Batch/candidate HTTP/access metrics including request counts, 403/429/5xx/challenge counts, retry counts, elapsed time, host counts, and cheap response-byte accounting,
- persist those metrics as incremental JSONL runtime output under `output/metrics/`, not as Catalog rows or a new metrics database,
- print a concise Batch summary and metrics path on normal and abnormal completion,
- do not fetch/read response bodies solely for metrics,
- do not add guessed 100/200-page session cutoffs or automatic browser restarts before real request/elapsed/challenge data has been observed; existing `--limit` can bound an operator-run when desired,
- do not add proxy/IP rotation, UA/fingerprint spoofing, CAPTCHA/WAF bypass, challenge solving, browser/profile/session cycling, or random timing intended to disguise automation.

Implementation remains intentionally split into four reviewable phases:

1. shared settings/pacing + Magapoke ordering,
2. Work Ticket grant-only,
3. Premium/all grant-only,
4. access fail-safe + JSONL metrics.

Phase 1 must explicitly test `save -> one pacing delay -> initial go_next -> wait_for_change`, no delay on AD, no reapplication on adapter retry, no timeout-budget consumption, and preservation of existing Manga ONE / BookWalker / Magapoke navigation semantics.

See the authority document for acceptance criteria and detailed semantics.
