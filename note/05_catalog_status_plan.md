# Catalog item status future plan

> **SUPERSEDED / CONSOLIDATED**
>
> The previously deferred Item status change is now part of the adopted Catalog v6 plan:
>
> `note/07_catalog_position_archive_plan.md`
>
> Current production code remains schema v5 until that plan is implemented.

The v6 plan supersedes this file's earlier decision to defer `skipped`.

Adopted future Item status set:

```text
pending
completed
skipped
external
```

The same v6 plan also adds a generic nullable `items.note` field.

Implementation details, migration rules, CLI behavior, acceptance criteria, and synchronization requirements are maintained only in:

```text
note/07_catalog_position_archive_plan.md
```

Do not implement from the historical contents of this file. Update the v6 plan instead.
