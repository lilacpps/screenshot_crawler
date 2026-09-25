# Catalog item status future plan

> **PLANNED / NOT YET IMPLEMENTED**
>
> This note records a future Catalog schema change candidate. The current implementation remains schema v5 and is unchanged by this note.

## Background

Catalog `items.status` currently accepts only:

- `pending`
- `completed`

Batch Planner / Executor process only `pending` items, so an item can currently be removed from future Batch execution by marking it `completed`.

A concrete case is an item that is intentionally unsupported or not worth crawling, for example a vertical-scroll episode. For now, such items may be manually treated as `completed` through the planned/manual status CLI rather than expanding the schema immediately.

## Current decision

Do **not** change the Catalog schema for this requirement yet.

For the immediate operational need:

- keep schema v5
- keep `items.status` as `pending | completed`
- add only a manual CLI to change an item between `pending` and `completed`
- do not add `skipped` yet
- do not add a dedicated `status_reason` column
- do not repurpose unrelated existing columns such as `order_label` or `source_targets.priority`

This keeps the change small and avoids a schema migration solely for a low-volume manual exception.

## Future schema candidate

When the next meaningful Catalog schema revision is needed, reconsider adding:

### 1. `items.status = skipped`

Expected semantic distinction:

- `pending`: eligible for normal Batch planning
- `completed`: processing is considered complete
- `skipped`: intentionally excluded from processing without claiming that a normal crawl completed

Adding `skipped` requires changing the SQLite `CHECK` constraint on `items.status`, so it should be handled as a real schema migration rather than an application-only enum change.

### 2. Generic item note field

If a free-text field is added, prefer a generic field such as:

```text
items.note TEXT
```

rather than a narrowly scoped field such as:

```text
items.status_reason TEXT
```

The intended use is lightweight human-maintained context, for example:

```text
vertical-scroll episode; crawler intentionally not supported
```

or:

```text
already archived manually
```

The note is informational metadata and should not itself drive Batch eligibility.

## Migration timing

Do not create schema v6 only for this feature unless the operational need becomes large enough to justify it.

Prefer bundling this with the next substantive Catalog schema revision, at which point the migration can include:

- `pending | completed | skipped` status semantics
- optional generic `items.note`
- corresponding model / service / export / CLI / tests updates

Until then, manual `pending/completed` status control is the accepted workaround.
