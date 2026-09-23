# Magapoke Access / Resource Plan (planned, not yet implemented)

Status: **PLANNED / NOT YET IMPLEMENTED**.

Authorities:

- shared pacing / AccessGuard / metrics / generic resource selection / grant-only: `docs/ACCESS_CONTROL_AND_PACING.md`,
- Magapoke-specific resource behavior: `docs/MAGAPOKE_BATCH_ACCESS.md`.

This note exists to keep the adopted Magapoke plan synchronized without rewriting `note/03_magapoke.md` as though planned behavior were already implemented. `note/03_magapoke.md` remains the current-implementation snapshot until each phase lands; implementations must update that current-state note in the same change.

The shared plan is also summarized in `note/04_access_control_plan.md`.

Planned Magapoke-specific changes:

- keep Discovery latest-first,
- order Batch candidates within a Work by `published_at ASC` (NULL last), then `source_id ASC`,
- expose `work_ticket` and `premium_ticket` as Magapoke instances of the generic access-resource contract,
- provide resource pass order as `work_ticket` then `premium_ticket` from the Magapoke policy/integration rather than hard-coding those names in Batch,
- add generic-compatible grant-only support for `work_ticket`, `premium_ticket`, and `all`,
- define `all` as Work Ticket pass -> Catalog replan -> Premium Ticket pass,
- persist Work-scoped Work Ticket `last_consumed_at` separately from episode/Premium state,
- use `work_ticket_cooldown_hours: 23` as a local negative gate before site access,
- after cooldown, keep live UI authoritative; unavailable Work Ticket is an expected skip and does not reset the cooldown timestamp,
- respect Magapoke UI priority: do not bypass an available/required Work Ticket to force Premium Ticket,
- Premium-only resource pass skips candidates whose normal UI requires Work Ticket,
- retain live Premium Ticket balance checks and stop Premium attempts at zero,
- retain the existing conservative `access_granted_until = consumed_at + 71 hours` behavior,
- keep resource switching explicit: a Work Ticket attempt never silently consumes Premium and a Premium attempt never silently consumes Work Ticket,
- fail closed on ambiguous access UI or classification failure.

Shared behavior applied to Magapoke through `docs/ACCESS_CONTROL_AND_PACING.md`:

- root `crawler.yaml`,
- `page_turn_delay_ms: 1000`,
- `inter_candidate_delay_ms: 3000`,
- CONTENT pacing after save/progress and before initial `go_next`, outside timeout/retry budgets,
- no pacing for AD, loading polling, same-content waits, ticket confirmation, or adapter retries,
- per-site 403/429/challenge/CAPTCHA stop policy,
- relevant-host filtering,
- distinct `challenge_detected` and `captcha_detected` reasons,
- conservative visible CAPTCHA detection,
- no automatic retry/reload/solve/bypass through challenge/CAPTCHA,
- incremental JSONL Batch metrics under `output/metrics/`, including abnormal stops,
- no guessed 100/200-page session threshold or automatic browser restart without evidence.

Implementation follows the shared repository-wide phases:

1. runtime settings/pacing + Magapoke ordering,
2. shared AccessGuard + metrics wired to Magapoke/Manga ONE/BookWalker,
3. generic access-resource selection contract,
4. generic grant-only + Magapoke Work Ticket,
5. Magapoke Premium/all,
6. cross-site regression and live verification.

Key regression requirements include:

- `save -> one pacing delay -> initial go_next -> wait_for_change`,
- no pacing on AD or adapter retry,
- pacing outside timeout budgets,
- existing Magapoke/Manga ONE/BookWalker navigation semantics preserved,
- relevant-host 403/429 stop while unrelated third-party 403/429 do not,
- explicit challenge and visible CAPTCHA stop without automatic solve/retry,
- metrics survive abnormal stop,
- grant-only does not capture/package/complete,
- generic Batch contains no Magapoke resource-name branching,
- existing Magapoke native capture, ticket confirmation, and 71-hour grant behavior remain covered.

See the authority documents for detailed acceptance criteria and non-goals.
