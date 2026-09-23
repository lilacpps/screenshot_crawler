# Access control documentation change summary

The access-control plan was reorganized so shared behavior is no longer specified as Magapoke-only.

Shared authority now covers:

- per-site runtime pacing settings,
- exact delay/timeout boundary,
- relevant-host HTTP 403/429 fail-safe,
- explicit challenge detection,
- visible CAPTCHA detection and stop behavior,
- incremental JSONL access metrics,
- generic access-resource selection and resource-pass ordering,
- generic grant-only semantics.

Magapoke-specific authority now covers:

- `work_ticket` / `premium_ticket`,
- Work Ticket cooldown/state,
- Premium live balance,
- Work Ticket priority,
- Magapoke `all` resource-pass order,
- Magapoke candidate ordering,
- conservative 71-hour grant behavior.

The implementation plan is split into six reviewable phases in `ACCESS_CONTROL_AND_PACING_PLAN.md`.
