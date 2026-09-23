# Magapoke Access / Batch Plan (planned, not yet implemented)

Status: **PLANNED / NOT YET IMPLEMENTED**.

Authority: `docs/MAGAPOKE_BATCH_ACCESS.md`.

This note exists to satisfy note synchronization for the adopted Magapoke Batch/ticket/load-control specification without rewriting `note/03_magapoke.md` as though the behavior were already implemented. `note/03_magapoke.md` remains the current-implementation snapshot until each phase lands; implementations must update that current-state note in the same change.

Planned changes:

- keep Batch sequential; do not add configurable concurrency,
- add root `crawler.yaml` with safe code defaults for Magapoke:
  - `page_turn_delay_ms: 1000`,
  - `inter_candidate_delay_ms: 3000`,
  - `work_ticket_cooldown_hours: 23`,
- keep Discovery latest-first,
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
- add relevant-host HTTP 403/429 fail-safe stop behavior,
- add lightweight Batch/candidate HTTP/access metrics including request counts, 403/429/5xx, retry counts, elapsed time, host counts, and cheap response-byte accounting,
- do not add proxy/IP rotation, UA/fingerprint spoofing, CAPTCHA/WAF bypass, or random timing intended to disguise automation.

Implementation is intentionally split into four reviewable phases: settings/delays/order; Work Ticket grant-only; Premium/all grant-only; HTTP fail-safe/metrics. See the authority document for acceptance criteria and detailed semantics.
