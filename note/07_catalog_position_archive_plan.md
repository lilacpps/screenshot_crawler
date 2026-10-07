# Catalog position / archive naming / item status plan

> **P1-P4 IMPLEMENTED; P5 PLANNED / NOT YET IMPLEMENTED**
>
> This note is the adopted implementation plan for Catalog schema v6 and the later
> display-position/archive phases. Catalog schema v6/P1, Discovery position
> assignment/P2, Batch archive naming/P3, and existing-archive renumbering/P4 are
> implemented; the real Catalog/output rollout in P5 remains planned.
>
> Codex must keep this note synchronized while implementing the plan. When a phase is completed,
> update the corresponding section from PLANNED to IMPLEMENTED and record any verified deviations.
> Do not silently change the adopted semantics.

## 1. Purpose

The next Catalog revision bundles three related changes that should be implemented together:

1. persist a site/discovery-scope display position for each Source,
2. use that position in archive naming so special/kanji-numbered episode labels sort correctly and ordinary same-label collisions disappear,
3. expand Item status semantics so intentionally skipped or externally acquired content is not misrepresented as crawler-completed.

A migration tool for already-created ZIP archives is also required.

Primary examples:

```text
001-第一話
002-第二話
003-番外編
004-第三話
```

The numeric prefix is **display order**, not episode number.

## 2. Pre-P1 state

Before P1, Catalog schema v5 had:

```text
items.status = pending | completed
items.order_key
items.order_label

sources.site
sources.external_id
sources.discovery_key

crawl_runs -> artifacts
artifacts.locator
```

There is no persisted display-position field.

`order_key` is intentionally only a generic natural-order key when an episode/volume label can be parsed safely. It must not be repurposed as the new display position.

Packaging derives the archive stem from generic output metadata. P3's Batch
Planner supplies a generic `{site}-{external_id}` disambiguator only for a
same-site, same-Work sanitized-stem collision across distinct Item IDs.

A successful re-crawl creates a new CrawlRun and a new Artifact row. It does not replace the previous CrawlRun/Artifact history.

## 3. Schema v6

Adopt Catalog schema v6 with the following changes.

### 3.1 Source display position

Add:

```text
sources.display_position INTEGER NULL
CHECK(display_position IS NULL OR display_position >= 1)
```

Semantics:

- the value is a 1-based position in the site's complete work listing,
  ordered oldest-to-newest,
- lower values are older/earlier in that complete listing,
- higher values are newer/later,
- it is not an episode number,
- it is Source metadata because the authority is the site/discovery listing, not cross-site Item identity,
- it may change after a later full Discovery,
- NULL means no safe position has been established yet.

Do not add a global UNIQUE constraint for `display_position`.

The practical position namespace is the site's complete work listing, normally
identified by `(site, discovery_key)` and its listing identity. Different sites
may legitimately use the same numeric position. A bounded scope does not create
a new position namespace and must not renumber the selected subset.

### 3.2 Item status

Expand `items.status` to:

```text
pending
completed
skipped
external
```

Semantics:

- `pending`: eligible for normal Batch planning,
- `completed`: successfully acquired by this crawler,
- `skipped`: intentionally excluded from acquisition,
- `external`: already acquired outside this crawler and therefore not needed from normal Batch.

Only `pending` is Batch-eligible.

Do not add Item states such as `running`, `failed`, or `retry`; run lifecycle already belongs to `crawl_runs.status`.

### 3.3 Item note

Add:

```text
items.note TEXT NULL
```

This is human-maintained informational context and must not itself affect Batch eligibility.

Examples:

```text
vertical-scroll; intentionally unsupported
already archived manually
```

### 3.4 completed_at

Adopt the following invariant:

- `completed` may have `completed_at`,
- switching an Item to `pending`, `skipped`, or `external` clears `completed_at`,
- changing `note` does not change status or `completed_at`.

### 3.5 Migration

The v5 -> v6 migration must use the existing explicit `catalog migrate` flow:

- automatic pre-migration backup,
- one transaction,
- rollback on failure,
- final schema validation,
- no implicit runtime migration.

Because the Item status CHECK constraint changes, rebuild the `items` table safely if required by SQLite. Preserve Item ids and all existing values.

Existing Sources migrate with `display_position = NULL`.

## 4. Position authority and ordering

### 4.1 Canonical order

Each Discovery Adapter already owns site-native listing interpretation and canonical discovery order.

The shared position contract is:

```text
canonical Discovery order: newest -> oldest
display_position:          oldest = 1 ... newest = N
```

Site-specific DOM/layout differences remain Adapter concerns.

Observed examples:

- Magapoke: visible listing is newest-first,
- Jump+: content is split across ranges/pages; the left/top side represents newer content,
- Manga ONE: content is paginated; the first/top side represents newer content,
- Zeblack: DOM validation observes oldest-first, while production Discovery currently reverses it to canonical latest-first.

Do not derive position by parsing Arabic numerals, kanji numerals, titles, or episode labels.

### 4.2 Bounded Discovery

For a bounded Watchlist target, position remains relative to the site's
complete listing, including content outside the configured scope. The bounded
scope only filters which records are synchronized.

Example:

```text
complete listing:
oldest A=1 ... newest H=8

configured bounded scope:
D -> display_position 4
E -> display_position 5
F -> display_position 6
G -> display_position 7
```

Bounded-capable Adapters that already enumerate the complete listing attach a
run-local global-position hint before applying the scope slice. The hint is not
a schema column and is committed only after safe Discovery completion.

If the configured scope changes, the selected set changes but its positions do
not reset. A bounded run without global hints fails closed rather than falling
back to scope-local `1..N`.

Archive collision handling remains fail-safe and must not assume position alone
is globally unique across sites or Works.

## 5. Full Discovery position behavior

A successful full Discovery is authoritative for positions inside its own discovery scope.

Requirements:

1. validate and collect the complete canonical record set required by the existing full Discovery contract,
2. use Adapter-provided complete-listing positions when bounded; otherwise determine positions oldest -> newest as `1..N` from the unbounded canonical stream,
3. persist those positions for every observed Source in the scope,
4. allow existing positions to change,
5. do not change Item status,
6. do not use position changes as cross-site merge evidence.

For bounded full Discovery, update only the configured scope. Existing Sources outside that scope must not be renumbered or reconciled by this position update, and selected Sources retain their complete-listing positions.

Position assignment should be committed only after the run has satisfied the existing full-Discovery completeness contract. An incomplete full Discovery must not partially rewrite established positions.

## 6. Incremental Discovery position behavior

Incremental Discovery must also assign positions because newly discovered content is normally crawled soon after discovery and archive naming requires a position.

### 6.1 Normal append case

When the Adapter provides complete-listing global hints, Incremental Discovery
uses those hints as the authority. Otherwise unbounded Incremental Discovery
retains the same latest-side append model already used by its early-stop
behavior. Bounded Incremental Discovery without hints fails closed.

For the unbounded no-hint append case:

1. collect the Sources observed during the current incremental run,
2. read the maximum non-NULL `display_position` only among those observed Sources,
3. when the run reaches a normal incremental stopping condition, order the observed Sources whose position is NULL oldest -> newest,
4. assign consecutive positions starting at `observed max + 1`.

Positioned Sources in the same discovery scope that were not observed during
the current run, including historical or unavailable Sources, do not contribute
to the incremental baseline.

Example:

```text
existing max = 100
observed canonical order = 103, 102, 101, known-100

persist:
101 -> position 101
102 -> position 102
103 -> position 103
```

### 6.2 Failure behavior

Do not finalize new positions when the incremental run ends as incomplete/error before a safe normal stopping condition.

Newly created Source rows may exist because the current DiscoveryService streams writes. In that case their `display_position` may remain NULL. A later successful incremental/full run may fill it.

Existing established positions must not be rewritten by an incomplete incremental run.

### 6.3 Mid-list insertion

Incremental Discovery cannot reliably detect a newly inserted old/intermediate bonus chapter without enumerating the full scope.

If the site presents such an insertion in a way that incremental Discovery treats as latest-side new content, temporary append numbering is acceptable.

The next successful full Discovery is authoritative and may correct all positions in the scope.

## 7. Batch and archive naming

### 7.1 New order component

For an episode Source with a known display position, Batch keeps the position
separate from the ordinary output metadata and passes it as an optional archive
filename prefix:

```text
artifact_prefix = {display_position:03d}
metadata["order"] = order_label
```

Examples:

```text
001-第一話
002-第二話
003-番外編
004-第三話
1000-特別編
```

Three digits are a minimum width, not a maximum.

The generic package stem component order is:

```text
artifact_prefix-[title when sanitized title length < 50]-order-author[-artifact_disambiguator].zip
```

Examples:

```text
003-作品名-番外編.zip
103-第９５話-作者.zip
```

`artifact_prefix` is applied only to the archive/status filename stem. The
title remains in the library directory `genre/title`, so a position never
creates a `001-作品名` directory. The sanitized title is included in the
filename below 50 characters and omitted at 50 characters or longer.
`archive_position_prefix()` is the shared primitive
for converting a nullable `display_position` to the minimum-three-digit
prefix. `archive_metadata_for_catalog()` keeps `order` as the raw
`Item.order_label`; NULL position therefore retains the order/author filename
components without inference. If all filename components are empty, packaging
uses the `archive` fallback stem.

### 7.2 NULL position

During migration/partial implementation, a Source may have `display_position = NULL`.

Do not invent a position from `order_key`, Item id, Source id, title parsing, or kanji-number conversion.

During the transition, preserve the existing archive naming fallback for NULL positions. Before normal operation resumes after v6 migration, existing Watchlist targets should receive a successful full Discovery so positions are populated.

### 7.3 Shared naming helper

The logic that converts Work/Item/Source metadata into the desired archive order/stem must be shared by:

- Batch packaging preparation,
- archive renumber tooling.

Do not duplicate naming rules in the migration script.

Core packaging must remain Catalog-independent. Catalog/Batch code computes explicit metadata; packaging only consumes it.

## 8. Collision handling

The position prefix removes ordinary collisions such as repeated `番外編` / `おまけ` labels inside one scope, but it does not prove global uniqueness.

Possible remaining collisions include:

- different sites under the same Work,
- multiple discovery scopes under the same Work,
- legacy/manual artifacts,
- two distinct Sources whose final sanitized stem still collides.

Keep a generic packaging-only disambiguation safety path.

The long-term generic suffix shape may use stable Source identity such as:

```text
{site}-{external_id}
```

but it must only be added when necessary; do not make site/external-id suffixes part of every normal filename.

P3 replaces the former Manga ONE / Magapoke special-case collision logic with
the generic sanitized-stem collision rule, covered by Planner tests.

Never overwrite an existing destination archive.

## 9. Re-crawl semantics

Re-crawl remains explicit and conservative.

Operator flow:

```text
delete the existing ZIP manually
-> set Item status back to pending
-> run normal Batch crawl
```

Requirements:

- do not automatically delete an existing archive,
- do not automatically overwrite an existing archive,
- `completed -> pending` does not create a new Source,
- the same Item/Source/Target may create a new CrawlRun,
- a successful re-crawl creates a new Artifact row,
- previous CrawlRun/Artifact rows remain historical records.

If the old ZIP still exists, existing packaging collision behavior may stop the re-crawl. That is intentional.

## 10. Existing archive renumber tool

Provide a dedicated maintenance tool for archives already created without the
position prefix and for later full-Discovery renumbering. This is not a
separate migration for previously scope-local names; corrected Catalog
positions are handled by the normal P4 command.

The exact CLI name may be chosen during implementation, but the functional contract is fixed below.

### 10.1 Filters

Support:

- `work_key`,
- `site`,
- both together as AND filters,
- explicit all-target mode.

Do not accidentally operate on the entire library when no scope/filter was supplied.

Provide dry-run behavior before mutation.

### 10.2 Current Artifact selection

Handle at most one current archive Artifact per Source.

Selection rule:

1. find the newest successful CrawlRun for that Source that produced an archive ZIP Artifact,
2. select that current Artifact,
3. do not fall back to older CrawlRuns if the selected current Artifact's locator is missing on disk.

If the current locator does not exist:

```text
MISSING -> report and skip
```

This avoids confusing historical artifacts with current files.

Past Artifact rows are history and must not be rewritten merely because a newer re-crawl exists.

### 10.3 Old and new path authority

Old/current path authority:

```text
artifacts.locator
```

New filename authority:

```text
shared archive naming helper
using Work + Item + Source.display_position
```

Do not reconstruct the old filename from Source metadata.

This is intentional because legacy naming rules and old disambiguator suffixes may differ from the current rules.

### 10.4 Rename behavior

For every selected current Artifact:

- if locator file is missing: report MISSING and continue,
- if already at the desired path: report unchanged and continue,
- if desired path is occupied by a non-participating file: report COLLISION and skip,
- never overwrite.

Preflight the full rename plan before mutating files.

Use a two-stage rename when needed:

```text
old -> unique temporary path
temporary -> final path
```

This prevents false collisions when multiple participating files exchange/shift names.

### 10.5 Catalog update

After a successful rename:

- update only the selected current Artifact's `locator`,
- keep SHA-256 unchanged,
- keep byte_size unchanged,
- do not change CrawlRun,
- do not change Item status,
- do not rewrite older Artifact rows.

If filesystem rename succeeds but Catalog update fails, fail clearly and preserve enough output to repair the discrepancy manually. Prefer transaction/planning structure that minimizes this window.

### 10.6 crawl-status JSON

Packaging also stores:

```text
output/crawl-status/<genre>/<title>/<stem>.json
```

When a matching completion-status JSON exists and safely identifies the same old archive path:

- rename the status JSON to the new stem,
- update its `archive_path`.

If no matching status JSON exists, warn and continue; absence of this auxiliary file must not block a valid ZIP rename.

Do not mutate an unrelated status JSON merely because its filename resembles the target.

## 11. Status CLI

Extend the existing Item status CLI to support:

```text
pending
completed
skipped
external
```

It must continue to support read-only status inspection.

Provide a minimal way to set/clear `items.note` without directly editing SQLite. Exact CLI spelling may be chosen during implementation, but avoid a complex status workflow DSL.

Status mutation must not create CrawlRuns or Artifacts.

Discovery refresh must not overwrite the operator-maintained Item status or note.

## 12. Export / backup / maintenance

Catalog export must include the new fields:

- `items.note`,
- `sources.display_position`.

Backup remains schema-neutral.

Any maintenance script that depends on the Item/Source model must be reviewed for v6 compatibility.

## 13. Operational migration runbook

Because schema v5 code cannot use a migrated v6 database and v6 work spans schema + Discovery + Batch naming, finish currently needed crawling before beginning the migration rollout.

Recommended rollout:

```text
1. finish urgent crawling on current v5
2. implement and test schema v6 + position + naming
3. catalog migrate
4. run full Discovery once for each relevant Watchlist target
5. verify display_position population
6. run archive renumber dry-run
7. review missing/collision output
8. apply archive renumber
9. resume normal incremental Discovery / Batch operation
```

Keep the automatic pre-migration backup.

## 14. Implementation phases

### P1 - Catalog v6

IMPLEMENTED.

- schema + migration,
- Source display_position model/service support,
- Item status expansion,
- Item note,
- export,
- status/note CLI,
- migration tests.

P1 implementation details:

- Catalog runtime schema version is 6. `items.note` and nullable
  `sources.display_position` are required schema columns.
- Item statuses are `pending | completed | skipped | external`. Only `pending`
  remains Batch-eligible. Status changes through `CatalogService` clear
  `completed_at` for every non-`completed` status; note updates leave status and
  `completed_at` unchanged.
- `catalog migrate` performs the v5 -> v6 migration with the existing automatic
  pre-migration backup and transaction/rollback/final validation contract. The
  migration rebuilds `items` to replace its status CHECK constraint and initializes
  `note` and `display_position` to NULL while preserving existing row IDs/data.
- `catalog item-status <item_id> [pending|completed|skipped|external]` supports
  read-only inspection and status changes. `catalog item-note <item_id> "text"`
  sets/replaces a note, and `catalog item-note <item_id> --clear` clears it.
- CSV export includes `items.note` and `sources.display_position`.
- P1 alone did not assign display positions during Discovery and did not change
  Batch archive naming, collision handling, archive renumbering, or crawl-status
  JSON naming. P2 now assigns positions during safe Discovery completion. P3
  implements new Batch archive/status naming and generic collision handling;
  P4 now provides the local existing-archive/status renaming and Artifact
  locator update maintenance command. Real production rollout remains P5.

### P2 - Discovery position

IMPLEMENTED.

- full authoritative renumbering,
- incremental append numbering,
- incomplete-run safety,
- bounded-scope behavior,
- site regression coverage.

P2 implementation details:

- `DiscoveryService` keeps first-observed Source IDs in the Adapter's
  canonical newest-to-oldest yield order. Bounded-capable Adapters attach a
  run-local `global_display_position` after complete-listing validation and
  before scope slicing. It is not a persisted schema field.
- The run-local observed Source ID list is an ordered-set equivalent, so a
  duplicate observation is counted by the existing Discovery counters but is
  assigned only once.
- Normal full Discovery assigns `oldest=1 ... newest=N` only after normal
  exhaustion. Bounded full Discovery persists Adapter-provided complete-listing
  positions only within the yielded scope; it never scope-local-renumbers them
  and Sources outside that scope are untouched.
- Incremental `stable_boundary` and `known_streak` stops use available global
  hints as authority. Without hints, only unbounded incremental Discovery uses
  the maximum
  non-NULL position among Sources observed during the current run as the
  baseline. The currently observed Sources whose current position is NULL are
  reversed into oldest-to-newest order and receive `observed max+1`,
  `observed max+2`, ... . Positioned Sources in the scope that were not
  observed during the run, including historical or unavailable Sources, do not
  contribute. This includes Sources created by a previous incomplete
  incremental run and re-observed later.
- An unbounded incremental run that exhausts the scope normally is treated as
  full for position purposes and receives `1..N`, including when no baseline
  exists. Bounded incremental without complete-listing hints is incomplete;
  it never falls back to scope-local numbering. If an unbounded early-stop run
  has no observed non-NULL baseline, assignment is skipped and NULL is
  preserved as a fail-safe.
- `DiscoveryIncompleteError` never finalizes positions. Existing positions are
  unchanged and Sources created during the incomplete run may remain NULL.
  Item status, `completed_at`, and operator `note` are not changed.
- `CatalogService.set_source_display_positions()` validates all positions and
  all Source identities, then updates the batch in one transaction with
  `updated_at`; an empty assignment is a no-op. The assignment API permits
  duplicate numeric positions because no UNIQUE position constraint exists.
- Position calculation uses only records already yielded for the requested
  Discovery. Adapters perform any site-native complete-listing enumeration
  needed to calculate bounded hints before yielding their selected slice; the
  Service performs no additional pagination, DOM scan, HTTP request, or
  full-list access.

P5 remains planned: real Catalog/output rollout and live verification are not
part of the tested P4 maintenance implementation.

### P3 - Batch archive naming

IMPLEMENTED.

- `src/screenshot_crawler/batch/naming.py` provides shared Catalog naming
  helpers (`archive_position_prefix()`, `archive_metadata_for_catalog()`,
  `catalog_archive_stem()`, and `collision_source_ids()`) for Batch and P4.
  A non-NULL position is formatted as a minimum-three-digit filename prefix;
  NULL position preserves the legacy label fallback, and no order/title/id/
  identifier parsing is performed.
- Batch Planner passes `Source.display_position` as
  `BatchCandidate.artifact_prefix` and keeps the raw `Item.order_label` in
  `BatchCandidate.metadata["order"]`; title, author, and genre keep their
  existing Work metadata mapping. The Core packaging prefix affects only the
  archive/status stem, not the library directory.
- Generic collision detection uses the site-scoped planning snapshot across all
  Item statuses. It compares `archive_stem()` output without a disambiguator,
  grouped by `(Work.id, sanitized base stem)`, and marks a group only when it
  contains at least two distinct Item IDs. Same-Item multiple Sources do not
  count as a collision.
- Only candidates whose Source is in a real collision receive the generic
  `{site}-{external_id}` `artifact_disambiguator`. This replaces the previous
  Manga ONE non-numeric and Magapoke-only workarounds while retaining completed
  Item participation and sanitized-stem safety.
- Core packaging remains Catalog-independent and remains the final filename
  sanitization authority. Same-site planning collisions are handled by the
  Planner; cross-site or pre-existing filesystem collisions remain protected by
  `package_crawl_output()` raising `FileExistsError` without overwrite.
- P3 still does not rename existing ZIP archives, existing crawl-status JSON, or
  historical Artifact locators; those operations are isolated in the P4
  maintenance command described below.

### P4 - Existing archive renumber tool

IMPLEMENTED.

- `scripts/renumber_archives.py` is a thin wrapper over
  `screenshot_crawler.maintenance.archive_renumber`.
- Scope is explicit: `--work-key`, `--site`, both as AND filters, or `--all`.
  `--all` cannot be combined with another filter, and no-filter invocation is
  rejected. Default mode is dry-run; only explicit `--apply` mutates files or
  Catalog.
- `Artifact.locator` is the sole old-path authority. The selected current
  Artifact is the archive/zip Artifact from the newest successful CrawlRun that
  produced one. A successful run without an archive is skipped while looking
  older; once selected, a missing locator is `MISSING` with no historical
  fallback. Multiple archive ZIP Artifacts in that run are `AMBIGUOUS`.
  Non-filesystem storage is `UNSUPPORTED`, and `display_position = NULL` is
  `NO_POSITION` without inference.
- Desired stems use the same Catalog naming helpers as P3, including the full
  same-site collision snapshot and `{site}-{external_id}` disambiguator rule.
  The new path is only `Path(Artifact.locator).parent / <desired-stem>.zip`;
  title/genre changes never move the directory.
- The full plan is preflighted before mutation. Internal and external target
  collisions, including dependencies on an excluded participant, are
  `COLLISION`; existing files are never overwritten. ZIPs use
  `old -> unique temporary sibling -> final` two-stage renames, so shifts and
  swaps are safe. Apply performs a final old/target/temp recheck.
- Matching `output/crawl-status/<genre>/<title>/<old-stem>.json` is accepted only
  when parsed `archive_path` identifies the current old ZIP. For compatibility,
  explicit renumber also checks the legacy flat `output/crawl-status/<old-stem>.json`.
  `STATUS_MISSING` and
  `STATUS_MISMATCH` are warnings that do not block a ZIP rename. A matching
  status file is renamed safely and only its `archive_path` value is changed;
  target collisions block that Artifact.
- `CatalogService.update_artifact_locators()` performs one compare-and-set
  transaction after all filesystem/status mutations. It validates every
  Artifact id and expected locator before updating only `locator` and
  `updated_at`; SHA-256, byte size, state, CrawlRun, Item, and historical rows
  remain unchanged.
- Archive and matching status temporary names use separate short namespaces:
  `.archive-renumber-{artifact_id}.tmp` and
  `.status-renumber-{artifact_id}.tmp`. Rollback uses
  `.archive-rollback-{artifact_id}.tmp` and
  `.status-rollback-{artifact_id}.tmp`. These names do not include the original
  long archive basename, preserving Windows long-path mitigation and avoiding
  same-directory ZIP/status collisions.
- Catalog failure, including ordinary SQLite/database exceptions, attempts a
  two-stage filesystem/status rollback and reports
  `ERROR Catalog update failed; filesystem rollback completed`. If rollback
  cannot complete, `RECOVERY_REQUIRED` includes artifact, old/new/current/temp,
  and status paths. P5 real Catalog/output rollout and live verification are
  not performed by this implementation.
- Because the old path authority remains `Artifact.locator`, P4 can be applied
  again to archives produced by an earlier title-including naming rule, for
  example `作品名-001-第01話.zip` -> `001-作品名-第01話.zip` for a short
  title, including a matching crawl-status JSON sidecar. Long titles use the
  title-omitted target instead.
- Archives previously renamed using a scope-local position are repaired by the
  normal rollout: fixed full Discovery -> corrected `Source.display_position`
  -> `renumber_archives.py --dry-run` -> `renumber_archives.py --apply`. No
  dedicated migration is required.

### P5 - Real DB rollout / documentation cleanup

PLANNED.

- migrate production Catalog,
- full Discovery population,
- renumber dry-run/apply,
- live verification,
- update current-state notes,
- retire this plan once all behavior is represented by current implementation documentation.

## 15. Acceptance criteria

At minimum:

1. v5 -> v6 migration preserves all existing ids and data.
2. migrated Sources start with NULL display_position.
3. unbounded full Discovery assigns contiguous 1..N positions oldest -> newest; bounded full Discovery preserves complete-listing global positions and never renumbers the selected scope.
4. a later full Discovery may safely change existing positions.
5. unbounded no-hint incremental Discovery assigns new positions immediately after the existing max for normal latest-side additions; available global hints are authoritative.
6. multiple new incremental records receive oldest -> newest consecutive positions even when observed newest-first.
7. an incomplete incremental/full run does not partially overwrite established positions.
8. kanji-numbered and non-numeric labels require no parsing for archive order.
9. Batch-created archive names use the shared position prefix when available.
10. NULL position never triggers guessed numbering.
11. repeated bonus/special labels do not ordinarily collide once positions differ.
12. remaining cross-site/scope collisions are fail-safe and never overwrite.
13. `pending|completed|skipped|external` semantics are enforced by schema/service/Batch.
14. Discovery does not overwrite operator status/note.
15. completed -> pending permits a new CrawlRun using the same Source after the operator removes the old ZIP.
16. a re-crawl creates new CrawlRun/Artifact history instead of replacing historical rows.
17. renumber selects only the current successful archive Artifact per Source.
18. missing current locator is reported and skipped without falling back to historical artifacts.
19. renumber never derives the old path from metadata.
20. renumber preflight prevents overwrite and supports chained renames safely.
21. successful rename updates only the selected Artifact locator and matching crawl-status metadata.
22. work_key/site filters behave as explicit AND scope.
23. bounded Discovery without global hints fails closed and does not fall back to scope-local numbering.
24. existing access/quota/discovery identity behavior is not changed by this feature.

## 16. Non-goals

This plan does not introduce:

- cross-site automatic Item merge,
- kanji numeral conversion,
- fuzzy episode equivalence,
- automatic deletion/overwrite for re-crawl,
- automatic historical Artifact cleanup,
- content-based deduplication,
- position-based availability/access decisions,
- position-based cross-site equivalence.

## 17. Required note synchronization during implementation

As each phase lands:

- update this file's phase status and any verified implementation details,
- update `note/00_core.md` for current Catalog/Discovery/Batch/packaging behavior,
- update affected site notes when site-specific Discovery ordering behavior changes,
- update `docs/DISCOVERY_AND_BATCH.md` if the implemented contract changes the authoritative Discovery/Catalog/Batch specification,
- do not leave obsolete planned behavior presented as current behavior.

Once P5 is complete and all adopted behavior is represented in the authoritative/current-state docs, this plan may be reduced to a pointer or removed according to the repository note maintenance rules.
