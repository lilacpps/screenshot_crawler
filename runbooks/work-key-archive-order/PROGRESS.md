# Work-key acquisition scope / archive ordering — Progress

> Status: **P0-P5 and 2026-10-22 adapter follow-ups implemented/reviewed; final full suite completed (4,991 passed, 2 failures: one config-dependent, one unresolved timing failure; 0 skipped)**
> Main runbook: [README.md](README.md)
> Branch: `feature/work-key-archive-order`. P0-P3 checkpoint: `b0a4a37`; P4 Reviewer approved.
> Initial P0-P5 verification used isolated working copies and synthetic fixtures. Later adapter follow-up used bounded metadata-only public-page probes covering two Kadocomi works and verified the resulting flows only on isolated Catalog copies. No paid entitlement, reader/capture, ticket/quota action, or operational Catalog/Watchlist/Books write was performed.

## Phase gates

| Phase | Status | Evidence / next action |
|---|---|---|
| P0: Current contract / fixture | COMPLETE | Existing call paths reviewed; isolated synthetic fixture and baseline tests recorded below |
| P1: Watchlist + Catalog v7 | COMPLETE | implementation, focused tests and independent Reviewer APPROVE; see P1 record below |
| P2: Scope reconciler | COMPLETE | read-only dry-run, CAS apply, evidence gates, orphan handling; independent Reviewer APPROVE / BLOCKING 0 |
| P3: Batch integration | COMPLETE | normal/grant-only/deferred/replan filtering and consistency gate; 434 affected tests pass; independent Reviewer APPROVE / BLOCKING 0 |
| P4: Naming + renumber | COMPLETE | shared cross-site numbering and strict whole-work renumber; Reviewer APPROVE / BLOCKING 0 |
| P5: Verification + rollout | COMPLETE | isolated copy/synthetic verification, full-suite attribution, rollout docs, and independent final review complete; production rollout remains a separate operator action |

## Adopted constraints

- No site-crossing Item merge; stable Source.discovery_key; no same-site key reparenting.
- Watchlist.discovery_scope is the acquisition scope authority; no separate acquisition_scope YAML.
- archive_order opt-in is whole-work: all keys set or none.
- Exclusion does not change Item.status, Source.available/access_mode, source history or existing artifacts.
- Incomplete scope sync, unknown boundary, stale fingerprint, and filename collision fail closed.
- No automatic rename, delete, purchase or quota consumption during verification.
- GUI follows in a separate workstream after backend is stable.

## P0 — Current contract / fixture (2026-10-22)

### Observed current behavior

- Catalog is schema v6. `sources` has `discovery_key` and nullable
  `display_position`, with unique `(site, external_id)` identity; it has no
  acquisition flag or scope-sync/evidence table. The migration runner is
  explicit, backs up before migration and validates/rolls back the migration.
- `WatchlistTarget` currently carries `key`, `work_key`, `site`, `url`,
  `enabled`, and `discovery_scope`. Unknown `archive_order` is currently ignored
  on load and would be lost by a Watchlist rewrite. `_write()` also serializes
  fresh YAML and therefore drops comments. P1 must preserve all known fields;
  scope/order editing must not silently rewrite away comments.
- Discovery validates site-native bounded boundaries inside the Adapter.
  Bounded adapters can expose complete-list positions on yielded in-scope
  records, while `DiscoveryService` persists positions only for observed
  records. Existing out-of-scope Sources remain in Catalog and are not
  refreshed or marked unavailable by bounded full Discovery. A row's old
  `display_position` alone therefore cannot prove its current listing identity,
  complete-list membership, or position freshness after a target/listing
  change.
- Batch planning reads a read-only Catalog snapshot, calculates local quota
  capacity from all site Sources, then evaluates/selects candidates. Normal,
  explicit grant-only, deferred resolver and additional-resource paths are
  downstream of Planner output; grant resolver preparation begins before the
  Executor's candidate validation. Acquisition filtering must happen before
  candidate selection, with an additional current-flag/gate check before any
  resolver/site access. Quota history calculation must continue to see all
  Sources so excluded historical consumption is not forgotten.
- Shared archive naming currently uses site-native `display_position`. The
  maintenance command preflights locator-based file paths and supports
  two-stage renames, status sidecars and Catalog rollback. It can currently
  leave safe entries eligible for rename when another row is `ERROR` or
  `COLLISION`; this is not sufficient for opt-in work-wide numbering. Opt-in
  renumber must block the whole work if any participant is unresolved,
  conflicting, or has unsafe status/catalog state. A `STATUS_MISMATCH` warning
  and an `UNCHANGED` row also require explicit all-work policy before apply.
- Existing Catalog data APIs are not uniformly read-only: general getters open
  a connection that may create a parent directory, initialize schema, and
  commit. `read_works_items_sources_and_targets()` uses a read-only connection.
  Scope preview must use a genuinely read-only snapshot path and must not create
  a missing DB, parent directory, or lock file.

### Before/after behavior matrix

| Case | Current v6 / P3-P4 | Required work-key behavior |
|---|---|---|
| No `archive_order` for the work | Per-source `display_position` remains filename prefix | Preserve current filenames exactly |
| All keys have distinct `archive_order` | Order is not represented | Order keys numerically, then each key's acquisition-enabled sources by `display_position`, one sequence |
| Partial/duplicate order or key ownership conflict | Order ignored; same `(site, external_id)` cannot be reassigned to another key | Reject before sync, Batch, naming, or renumber |
| Zeblack range shrinks from 140 to 100; BookWalker has 2 volumes | Every source remains available to Batch under current access/status rules; ZIP prefixes are site-local | Zeblack 101-140 are retained but disabled and use no ordinal; BookWalker becomes 101-102 |
| Paid source inside/outside range | Access policy excludes paid from crawl, independently of discovery scope | In-scope paid reserves a number; out-of-scope paid does not |
| `enabled: false` key | Discovery selection only; existing Catalog rows remain | Keep scope assignment and numbering; do not discover it in the normal enabled-target pass |
| completed/skipped/external/unavailable source | Status/availability affect current Batch eligibility, not history | In-scope source reserves an ordinal regardless of these states |
| Boundary absent, NULL/duplicate position, stale/unproven listing | Bounded Discovery fails on invalid/missing site-native boundary; old stored position has no listing-proof version | Fail closed until successful full evidence binds target/listing identity, complete inventory and positions |
| Watchlist edited without sync / migration just completed | No existing reconciliation gate | Batch and opt-in naming fail closed on fingerprint/evidence mismatch |
| Work-wide renumber includes an unresolved participant | Existing maintenance may still rename other safe entries | Block all opt-in work participants; never delete/overwrite excluded ZIPs |

### Isolated fixture and baseline

- Added `tests/fixtures/work_key_archive_order/expanded.yaml` and
  `reduced.yaml`, using only `example.invalid` identities. They describe 140
  Zeblack positions (paid both inside and outside the narrowed boundary), two
  BookWalker volumes, a disabled Magapoke key with paid/unavailable rows,
  preserved completed/skipped/external items, and a same-site duplicate-source
  ownership probe.
- Added `tests/unit/test_work_key_archive_order_fixture.py`. It copies both
  Watchlists under pytest's temporary directory, builds a temporary v6 Catalog,
  creates the synthetic source graph and one existing ZIP/Artifact, then checks
  key/site separation, paid and status rows, disabled-key input, and artifact
  isolation. It does not use the repository `watchlist.yaml`, Catalog, or
  `output/Books`.
- Targeted baseline command (repo-local pytest temp/cache):
  `uv run --offline pytest --basetemp=.pytest-tmp-work-key -o cache_dir=.pytest-cache-work-key --tb=short -q tests/unit/test_watchlist.py tests/unit/test_catalog.py tests/unit/test_catalog_migrations.py tests/unit/test_discovery.py tests/unit/test_batch.py tests/unit/test_batch_executor.py tests/unit/test_deferred_grants.py tests/unit/test_batch_naming.py tests/unit/test_archive_renumber.py`
  produced 328 passed, 1 failed, 0 skipped. The failure was the existing
  `scripts.renumber_archives` test import because the pytest console entrypoint
  omitted the repository root from `sys.path`; there were 1,468 existing
  `pytest-asyncio` deprecation warnings.
- Rechecked that exact existing node and the new fixture test with
  `uv run --offline python -m pytest --basetemp=.pytest-tmp-work-key -o cache_dir=.pytest-cache-work-key --tb=short -q tests/unit/test_archive_renumber.py::test_cli_scope_usage_errors_are_exit_code_two tests/unit/test_work_key_archive_order_fixture.py`:
  2 passed, 0 skipped. `python -m pytest` puts the repository root on `sys.path`.
  The fixture test alone also passed (1 passed, 1 deprecation warning).
- Initial invocation against the machine's default pytest temp directory failed
  at fixture setup with an OS permission error while scanning
  `%TEMP%/pytest-of-kensu`. Subsequent runs used an isolated repository-local
  `--basetemp` and cache; the default temp tree was not modified.

### P0 review notes and implementation constraints

- Successful complete-list evidence must identify `(work_key, key, site,
  target URL/listing identity)`, the complete Source identity/position
  inventory and its digest. A boolean `complete` or positions from only the
  bounded yielded slice is insufficient. Incremental/partial mutation must
  invalidate stale evidence. Adapters without a supported identity/inventory
  hook remain unmanaged and fail closed.
- Scope sync must be preview/apply as separate service operations. Preview reads
  without creating or writing anything. Apply must recheck its Watchlist
  fingerprint, boundary evidence, source snapshot and target state before an
  atomic work-level Catalog update. Catalog-mutating Discovery/sync/Batch and
  renumber operations require shared per-Catalog job exclusion; no Watchlist
  rewrite happens inside the Catalog transaction.
- Migration initializes `acquisition_enabled=1` to preserve rows and history,
  but leaves synchronization/evidence unbootstrapped so migration alone never
  asserts boundary correctness or starts a work-key rename. Explicit unbounded
  legacy bootstrap safety is to be decided in P2; any scoped key requires a
  successful full inventory proof.
- Before entering a site resolver or any resource pass, validate current
  acquisition flags and synchronization fingerprints. Keep quota history
  input independent from the filtered candidate pool.
- For opt-in renumber, all-work preflight is atomic in policy as well as in file
  staging: any missing/unknown position, duplicate or unresolved key, unsafe
  Artifact/status state, collision, or Watchlist/Catalog mismatch blocks the
  entire work. Preserve the existing transaction/rollback machinery once this
  stronger gate passes.

No implementation-spec deviation was needed in P0. The new evidence and
whole-work preflight constraints make implicit assumptions in the runbook
explicit; they do not weaken its fail-closed behavior.

## P1 — Watchlist + Catalog v7 foundation (2026-10-22)

### Implemented

- Watchlist targets now round-trip optional positive-integer `archive_order`.
  Validation rejects partial or duplicate ordering within a `work_key` while
  preserving the prior meaning of `enabled` and `discovery_scope`.
- `watch add --archive-order` and the `watch list` output expose the setting.
- Watchlist writes retain comments for enabled-only scalar changes. Structural
  writes to comment-bearing files are refused before write; commentless writes
  are serialized, reparsed, normalized and compared against the exact requested
  target list before atomic replacement. A raw `#` is treated conservatively,
  including inside quoted multiline values or URL fragments, to avoid a
  false-negative comment detector.
- Catalog schema v7 adds `sources.acquisition_enabled INTEGER NOT NULL DEFAULT
  1 CHECK (acquisition_enabled IN (0,1))`, work-level sync metadata, complete
  discovery inventory evidence and positions. The schema validator checks the
  new tables' PK/FK/UNIQUE/CHECK contracts and required indexes.
- The explicit v6→v7 migration preserves Source/Item/Artifact identity,
  statuses, availability, positions and locators; new flags default to enabled
  for compatibility. It leaves scope sync and inventory proof empty. Migration
  does not reconcile sources or rename ZIPs.
- Catalog services expose atomic whole-work scope flag+marker storage and
  complete listing evidence records. Replacing a proof clears its old sync
  marker. Structural position/key changes invalidate stale proof and sync;
  metadata-only state refresh leaves them intact. `SourceInput` intentionally
  does not carry the flag so ordinary refresh cannot reset an existing value.

### Review findings addressed / remaining gate

- An initial YAML span patcher could delete or overwrite neighboring targets
  because PyYAML node end marks can point at the next mapping. It was removed
  from structural edits. The replacement refuses structural edits when raw
  comment-like text is present, and validates the full serialized target list
  before writing. Added regression cases cover first/middle/last deletion,
  multi-target order addition, omitted `enabled`, flow-style empty lists, and a
  multiline quoted label containing `#`.
- Fixed the evidence getter's `work_id` row handling before record/get tests and
  added v7 schema integrity checks for each newly introduced relation.
- Independent Reviewer approved P1 with BLOCKING 0. The Lead recorded the P1
  gate pass; P2 contract is now active.

### Verification

- `.venv\Scripts\python.exe -m pytest tests/unit/test_watchlist.py tests/unit/test_catalog.py tests/unit/test_catalog_migrations.py tests/unit/test_catalog_export.py tests/unit/test_cli.py --basetemp=.pytest-tmp-work-key -o cache_dir=.pytest-cache-work-key --tb=short -q` — **221 passed**, 397 existing `pytest-asyncio` deprecation warnings.
- `tests/unit/test_watchlist.py` — **43 passed**, 1 existing deprecation warning.
- `ruff check src/screenshot_crawler/catalog src/screenshot_crawler/watchlist
  src/screenshot_crawler/cli.py tests/unit/test_watchlist.py
  tests/unit/test_catalog.py tests/unit/test_catalog_migrations.py
  tests/unit/test_catalog_export.py tests/unit/test_cli.py` — **all checks passed**.
- No integration/live-site test, migration of the normal Catalog, or ZIP
  renumber was run. P1 only adds schema and storage foundations.

### P1 paths

`src/screenshot_crawler/watchlist/{models.py,service.py}`, `src/screenshot_crawler/cli.py`,
`src/screenshot_crawler/catalog/{__init__.py,export.py,migrations.py,models.py,schema.py,service.py}`,
`tests/unit/{test_watchlist.py,test_catalog.py,test_catalog_migrations.py}`,
`docs/DISCOVERY_AND_BATCH.md`, `note/00_core.md`,
`note/07_catalog_position_archive_plan.md`, and this runbook/progress record.

The comment-preservation policy is a small P1 safety refinement to the runbook:
commentless structural edits remain available through the CLI, while
comment-bearing structural edits require direct Watchlist editing until a
comment-aware YAML editor exists. It prevents silent loss/corruption and is
covered by no-write regression tests.

## P2 — Scope Reconciler / orphan handling (2026-10-22, COMPLETE)

### Implemented

- Added GUI-ready `ScopeReconciler.preview()` / `.apply()` service and
  `watch scope-sync --watchlist PATH --catalog PATH --work-key KEY
  (--dry-run|--apply) [--json]`. Preview uses a read-only SQLite snapshot and
  does not create a missing Catalog/parent/lock file. Apply reloads Watchlist,
  rebuilds the preview while holding the stable per-Catalog job lock, checks
  the revision token, and atomically writes every Source flag and the sync
  marker under `BEGIN IMMEDIATE`.
- Successful Full Discovery on the supported proof adapters records complete
  listing evidence only after Catalog finalization succeeds. The evidence binds
  target URL, site-native listing identity, ordered complete identities and
  `(external_id, position, in_scope)` digest. Incomplete Full runs invalidate
  old proof; Incremental and metadata-only refreshes do not claim complete
  evidence or unnecessarily invalidate unchanged membership/positions.
- Explicit sync is intentionally separate from Discovery. A successful Full
  run refreshes evidence only; a user must inspect `--dry-run` and then request
  `--apply` to change `acquisition_enabled`. This closes the gap where a Full
  run could succeed but another key in the same work still lacked proof. Scope,
  key, URL or position changes require rerunning Full as needed and then an
  explicit sync. Batch will enforce the marker in P3.
- First-time legacy bootstrap is allowed without listing proof only for an
  unscoped, unordered work whose current Watchlist keys/site/work ownership
  classify every existing Source; every such Source is assigned enabled.
  Scoped or archive-ordered works require complete Full evidence. This avoids
  forcing old unbounded works through a needless listing refresh while never
  bootstrapping a changed URL. Last-known per-key URL bindings are retained when
  keys are removed, so re-adding the same target is recognized while changing
  that URL still needs fresh proof.
- Removed-key Sources are retained and disabled; restoring the saved same key
  can re-enable them. Same-site cross-key reassignment, foreign ownership,
  unknown orphan keys, invalid/stale proof, position mismatch, partial source
  coverage and digest tampering block preview/apply.
- Added a stable advisory Catalog job lock: no preview lock artifact, same-task
  nesting works, competing task/process fails fast, and the stable lock path is
  never unlinked.
- At P2 close, site-native complete-inventory hooks were wired for Zeblack, BookWalker,
  Magapoke, Jump+, Manga ONE and Piccoma. Other adapters retain unbounded
  Discovery behavior; scoped/archive-order opt-in on an adapter without proof
  fails closed until a native identity/inventory hook exists.

### Specification adjustment

The runbook originally described the successful Full listing proof and the
scope flag commit together. Implementation keeps the security boundary but
separates those operations: Discovery writes evidence; an explicit
`scope-sync --apply` changes flags only after all required keys are proven.
This is safer across multi-key works because one key's successful Full run
cannot silently commit a partial work-wide assignment. Legacy no-scope,
no-order bootstrap is allowed only under the strict ownership conditions above
for compatibility. The P2 runbook and this record document the deviation.

### Verification

- Focused Catalog / Watchlist / Discovery / reconciliation / lock / fixture
  tests: **185 passed**.
- Six supported adapter Discovery unit suites: **180 passed**.
- Manga ONE local routed-HTML browser-backed Discovery integration:
  **15 passed**. Unbounded Full streams partial rows as before, while publishing
  proof only after normal pagination exhaustion.
- `.venv\Scripts\python.exe -m ruff check src tests`: **all checks passed**.
- The first focused run exposed removed-key re-add binding loss; retained
  per-key binding history fixed it. A follow-up verifies same-URL re-add works
  and changed-URL re-add remains blocked pending fresh Full proof.
- Expanded the shrink/re-expand history test to the acceptance scale: 140
  Zeblack Sources → 100 enabled / 40 disabled → all 140 enabled. The exact
  test passes and confirms stable Source IDs, completed Item statuses, CrawlRun
  and Artifact locator.
- No real site, production Catalog/Watchlist/Books output, paid access,
  migration apply, or ZIP operation was used.

### Independent review

- P2 Reviewer: **APPROVE, BLOCKING 0**. The reviewer confirmed fail-closed
  inventory digest checks, sync marker/binding retention, complete work-wide
  preview coverage, explicit proof-then-sync operation, and stable job-lock
  behavior.
- P3 must treat `configuration_json` as retained per-key binding history,
  which can include removed keys. The active Watchlist fingerprint describes
  only current targets; do not compare the retained JSON directly to an
  active-only Watchlist serialization. Gate on sync status/fingerprint plus
  current Source flags and ownership.

### P2 paths

`catalog/{service.py,job_lock.py}`, `watchlist/{fingerprints.py,reconcile.py}`,
`discovery/{base.py,models.py,service.py}`, supported site Discovery adapters,
`cli.py`, focused tests, `docs/DISCOVERY_AND_BATCH.md`, corresponding notes,
and this runbook/progress record. P2 review gate passed. P3 is active.

## P3 — Batch integration (2026-10-22, COMPLETE)

### Implemented

- `BatchPlanner` now requires an explicit Watchlist whenever the selected site
  has Catalog Sources. It resolves `Source -> Item -> Work` by the actual
  foreign keys and requires a synchronized snapshot for every represented
  `work_key`. The read pool is compared with the exact Source rows in the
  validated snapshot, so a concurrent scope apply/source mutation cannot leave
  a stale candidate pool in use.
- `acquisition_enabled=0` is skipped before Site Policy evaluation, quota
  candidate allocation, and access-resource eligibility. Skip reason is
  `acquisition_disabled`. `available_quota` continues to use the complete
  pre-filter Source history, preserving prior resource consumption after a
  scope shrink.
- The same Planner gate serves normal, explicit grant-only, deferred-resource,
  replan, and additional-resource passes. `BatchExecutor` checks current
  Catalog Work/Item/Source/Target identity, locator, pending/available/current
  access mode, acquisition flag, and requested resource before adapter or
  resolver creation, then repeats the gate for execution-time validation.
- CLI `batch plan` and `batch run` accept `--watchlist` and default to
  `watchlist.yaml`. Batch run holds the shared Catalog job lock. `--grant-only
  all` preplans every ordered resource before CDP connection, returns without
  Browser/login when all passes are empty, and still replans each resource
  immediately before execution.
- Watchlist edit / Discovery proof / Catalog sync remain separate. A successful
  Discovery only refreshes complete-list evidence; until explicit
  `watch scope-sync --apply` has stored the active fingerprint and flags, Batch
  fails closed. Batch does not visit the site to re-resolve a boundary.

### Verification

- Targeted affected Batch / Executor / naming / site-policy / CLI / deferred
  grant / acquisition-scope tests: **434 passed**, no failures or skips. The
  command used isolated pytest basetemp/cache paths.
- `test_batch_acquisition_scope.py` includes missing-Watchlist rejection,
  Item-ID-versus-Work-ID regression, excluded-before-policy with quota-history
  retention, scope-apply/planner TOCTOU rejection, forged target rejection
  before AdapterRegistry use, and empty `grant-only all` without Browser
  connection or quota mutation.
- No real site, Browser/CDP, purchase, ticket/quota consumption, normal
  Catalog/Watchlist, or Books/output directory was used.
- Independent Reviewer: **APPROVE, BLOCKING 0**. Final review confirmed the
  fail-closed planner/executor gate, exact candidate identity/resource checks,
  and synchronized current-state docs/notes. The final note correction records
  the Batch gate as implemented while retaining P4 numbering/renumber as
  pending.

### P3 paths

`src/screenshot_crawler/{batch/planner.py,batch/executor.py,cli.py,watchlist/reconcile.py}`,
`tests/unit/test_batch_acquisition_scope.py`, updated isolated Batch/CLI fixtures,
`docs/DISCOVERY_AND_BATCH.md`, `note/00_core.md`,
`note/07_catalog_position_archive_plan.md`, this README and progress record.

P3 Reviewer **APPROVE / BLOCKING 0**. The phase is complete; P4's implemented
shared archive plan, work-wide renumber and strict preflight are recorded below.

## P4 — Cross-site naming and safe renumber (2026-10-22, COMPLETE)

### Implemented and reviewed

- Batch and renumber consume the same pure work-wide archive plan. It sorts all
  current keys by `archive_order`, then includes every `acquisition_enabled=1`
  Source in site `display_position` order. Item status, paid/free state,
  availability and Discovery `enabled` do not remove reserved numbers. A
  no-order work retains the prior site-local naming; a partial order fails.
- Planner, normal Executor, grant-only and deferred resolver paths validate
  all-site existing names/status before site access, and revalidate candidate
  Catalog identity, metadata, ownership and output-path occupancy. A completely
  unmanaged orphan Work is skipped before policy evaluation so an unrelated
  site run can proceed; its full Source history remains in quota accounting.
- Renumber supports one managed Work across all sites, `--watchlist`,
  `--catalog`, `--status-dir`, dry-run/apply and single-document `--json`.
  Managed partial `--site` renumber is rejected. Every apply rebuilds and
  compares the current plan under the Catalog job lock, including legacy
  preview→managed-state transitions. Preflight validates current ZIP SHA-256 /
  byte size, expected names, status sidecars, collisions, all-work Artifact
  locator aliases and excluded-file occupancy. It never deletes/overwrites an
  excluded ZIP. Strict blockers prevent partial apply.
- Failure recovery handles ZIP/status rename exceptions before and after the
  underlying rename, Catalog commit followed by interruption, locator CAS,
  status restoration and swap cycles. Recovery is reported as complete only
  after the original files/sidecars/hashes/locators are verified; otherwise
  the output includes `recovery_required` and actual paths/locators.
- Scope preview reports exact ordinal changes using the prior target order when
  available; if there is no known baseline it reports the old number as
  unknown rather than claiming unchanged.

### Verification

- Focused affected Batch / Executor / naming / deferred grant / scope /
  renumber tests: **237 passed**. Standalone `test_archive_renumber.py`:
  **40 passed**. Ruff for `src tests scripts/renumber_archives.py`: passed.
- Focused command used short isolated paths after a deeper basetemp reached a
  Windows path-length limit while writing one diagnostic trace. The same test
  then passed from `output/p4t-batch`; no test contract was changed for that
  environment limitation.
- P4 independent Reviewer: **APPROVE / BLOCKING 0**.
- Root synthetic E2E: 144 Sources shrink to 104 numbered Sources: Zeblack
  001–100, BookWalker 101–102, in-scope paid Magapoke 103–104; paid Zeblack
  rows outside scope consume no number. Both site Batch plans block stale
  existing names before renumber. Two ZIP/status rows were renamed with
  matching hashes/locators; excluded ZIPs were untouched. Re-expansion restored
  all 144 original Source IDs/statuses and BookWalker became 141/142.
- Root cross-site swap E2E passed: changing key order moved existing Zeblack /
  BookWalker ZIPs and status metadata to their new ordinals, with content hashes
  and Catalog locators still matching their Sources.
- Root rollback injection passed all eight ZIP/status rename stages after the
  filesystem rename itself succeeded and raised `KeyboardInterrupt`, plus a
  Catalog commit-then-interruption case. Files, status bytes, hashes, Catalog
  locators were restored and generated temp files were absent.
- `renumber_archives.py --json` root verification returned one parseable JSON
  document in dry-run/apply/error cases and did not mutate copy files during
  dry-run. A summary counter defect (`errors` zero while error entries existed)
  was fixed before this review.
- The full pytest/ruff run is led by root in short ignored `output/ft` and
  `output/fc` paths. Its first pass exposed existing browser integration tests
  that still constructed a planner without the newly required Watchlist. Those
  test fixtures were updated to create/sync explicit isolated legacy-unscoped
  Watchlists; the final complete rerun result will be recorded below.

### P4 review findings and fixes

- A Batch preflight originally received only the selected site's Sources and
  missed ordinal drift on another site. It now validates all current Work
  Sources. A regression checks a BookWalker ZIP mismatch before a Zeblack
  candidate can access its site.
- A pending candidate whose intended output path was already occupied by its
  own prior ZIP could pass preflight and consume quota before packaging raised
  `FileExistsError`. Candidate destination occupancy now blocks before access.
- Grant-only/resolver entry now shares the work-wide naming guard and compares
  fresh metadata/current Catalog identities; forged stale candidates are
  rejected before adapter/resolver creation.
- Strict renumber now rejects selected input paths aliased by excluded,
  historical or cross-Work Catalog artifacts and rejects duplicate status
  sidecars rather than leaving an orphan copy. Catalog locator validation is
  protected by `BEGIN IMMEDIATE`; post-commit interruption compensates locators
  before filesystem rollback.
- Applying a legacy preview after a Work becomes managed now rebuilds and
  compares current authority, rejecting the stale preview with zero mutations.

### P4 paths

`src/screenshot_crawler/{archive_order.py,batch/archive_guard.py,batch/naming.py,batch/planner.py,batch/executor.py,catalog/service.py,cli.py,maintenance/archive_renumber.py,watchlist/reconcile.py}`,
`scripts/renumber_archives.py`, related unit/integration fixtures,
`docs/{ARCHITECTURE.md,DISCOVERY_AND_BATCH.md,BOUNDED_DISCOVERY.md,BOOK_NAMING_RULES.md}`,
`docs/DECISIONS.md`, `note/{00_core.md,07_catalog_position_archive_plan.md}`,
site notes, this runbook/progress, and `COPY_VALIDATION.md`.

## P5 — Isolated copy verification and operator rollout (2026-10-22, COMPLETE)

### Copy-only evidence

- Root created a schema-neutral SQLite backup and raw Watchlist seed under the
  ignored `output/work-key-archive-order-p5/baseline/` path. P5 used only a
  separate working copy. No operational migration, scope apply, renumber,
  purchase, ticket/quota consumption or live-site action was run.
- The v6→v7 working-copy migration preserved ordered-row digests of all old
  columns in all seven legacy tables: works 226 rows; items/sources/targets
  36,701 each; runs 13,819; artifacts 11,236; quota rows 138. New Sources
  remained enabled by migration default while evidence and sync markers stayed
  empty. All 11,236 working-copy Artifact locators were remapped into the
  isolated output root; 42 ZIP/status assets were copied for verification.
- Repeated copy CLI dry-runs/plans preserved file bytes and mtimes. The scoped
  `spy-family` copy, which has no v7 complete Full evidence, correctly blocked
  Scope sync and Batch; no synthetic proof was added. An unscoped legacy
  `ryuurou-no-mahoro` copy safely bootstrapped and planned without quota change.
  Its strict renumber preview found exactly two existing Catalog SHA/size
  drifts (Sources 1364 and 1365); P5 left those files/catalog rows unchanged
  and does not claim a successful renumber for that Work.
- The documented copy-locator recipe was independently run against a throwaway
  synthetic source/copy: all 4 Artifact locators and 4 status references were
  remapped inside `COPY_ROOT`, and isolated renumber `--apply --json` moved 2
  copied ZIP/status pairs. Every source file's bytes and mtime stayed
  unchanged. Negative checks rejected both the original Catalog as the target
  and an overlapping original Books root before changing database bytes;
  evidence is `output/work-key-archive-order-p5/document-copy-validation-report.json`.
- Copy verification, CLI outputs and all rollback/E2E reports are under ignored
  `output/work-key-archive-order-p5/working/` and `synthetic-final/`; the
  immutable baseline seed remains unchanged.
- The user-facing docs now include current P4 behavior, supported scope-sync /
  renumber commands, copy-first migration sequence, rollback handling, a
  locator/status remap recipe and resolved-path containment gate for isolated
  renumber apply, and current notes for the complete-listing proof adapters
  available at initial P5 completion.
  `docs/DECISIONS.md` records the acquisition-scope / archive-order decision
  and why Full evidence refresh is separate from work-wide flag apply.
  At initial P5 close, the Hanayume, Younganimal, Kadocomi, and ComicFUZ hooks
  had not yet been implemented, and Comic DAYS had inventory evidence only.
  The site follow-ups below supersede that initial-coverage snapshot.

### Comic DAYS archive-order follow-up (2026-10-22)

- Added the adapter-owned complete-listing inventory hook to Comic DAYS using
  its already validated full Atom/readable-product listing. The proof binds the
  validated native series identity (`comicdays-series:<id>`) and preserves the
  adapter's latest-first identities with Core-compatible positions `N..1`.
- At this follow-up checkpoint, Inventory is published only after normal Full
  iterator exhaustion. Adapter reuse resets prior inventory; incremental and
  early-closed runs do not publish proof. DiscoveryService persists evidence
  only after successful Catalog finalization. At that checkpoint Comic DAYS
  was still unbounded-only; the F2 follow-up below adds `discovery_scope`.
- End-to-end synthetic test verified Comic DAYS plus BookWalker numbering,
  including paid and completed Comic DAYS rows reserving ordinals, failed Full
  invalidating scope sync, and Incremental not restoring proof.
- Final combined follow-up regression command covering
  `test_comicdays_discovery.py`, `test_discovery.py`, and
  `test_scope_reconciler.py` passed **111 tests**, 595 existing warnings, in
  23.56 seconds. No full-suite rerun was needed for this adapter-local change;
  the full-suite result below predates this follow-up.
  Root's affected shared regression run before this site-local change passed
  **151 tests**, 397 existing warnings. No live-site or paid/quota action was
  performed.
- Root's browser-backed Discovery-only integration selection passed **3
  passed, 106 deselected, 0 skipped, 5 warnings** using the existing routed
  Chromium test fixture; it exercised valid listing, count mismatch, and
  native feed-series identity mismatch without live-site access. The command
  and JUnit report are `tests/integration/test_comicdays_adapter_browser.py
  -k discovery_browser` and
  `output/comicdays-archive-order/browser-discovery.xml`.
- At this point in the chronology, the complete-listing inventory-hook count
  was seven; Comic DAYS still rejected bounded scopes. The subsequent follow-up
  below adds four hooks and completes Comic DAYS bounded support.
- Follow-up lint `.venv/Scripts/python.exe -m ruff check src tests
  scripts/renumber_archives.py` passed, as did `git diff --check` (Git emitted
  only existing LF/CRLF conversion notices for working-tree files).
- Independent final follow-up review: **APPROVE, 0 blocking findings**.

### Remaining adapter coverage and inventory-history follow-up (2026-10-22)

- **F1 — Hanayume, Younganimal, ComicFUZ:** added complete-listing inventory
  capture from each adapter's already validated full listing and existing
  global positions. Younganimal account-only rows remain outside the public
  inventory. Evidence is published only after normal Full exhaustion and
  successful Catalog finalization. Incremental, access-classification, and
  incomplete-run behavior remains intact. Independent Reviewer approved the
  material change with **0 blocking findings**. Routed browser Discovery for
  the three site modules passed **121 tests, 13 warnings, 0 skipped**.
- **F2 — Comic DAYS bounded Discovery:** added canonical same-series boundary
  validation and inclusive range selection over its validated complete
  Atom/readable-product listing. Full-list positions retain the latest-first
  `N..1` Core contract; successful Full proof and explicit scope-sync remain
  separate. The initial hook checkpoint passed a combined **111-test**
  Comic DAYS / Discovery / Scope regression and **3 passed, 106 deselected**
  routed-browser cases. The final boundary/scope selection passed **55 unit
  tests and 17 selected browser tests**. These are separate checkpoint and
  final-selection counts. Independent Reviewer approved with **0 blockers**.
- **F2.5 — Kadocomi opt-in native inventory and bounded scope:** for a target
  with `discovery_scope` or `archive_order`, the adapter validates the exact
  work-bound native `firstEpisodes` and `latestEpisodes` arrays, counts,
  identities/UUIDs/types, explicit positive `episodeNo`, active state, and
  reverse order. The legacy unconfigured path remains public-list-only and
  does not infer positions. Bounded metadata-only public-page probes covered
  two works and observed 123 rows for `KC_004915_S` and 33 rows for
  `KC_011605_S`; isolated
  copy checks assigned positions 001–123 and 001–033 while retaining inactive
  observed rows. Native episode-number gaps were not fabricated. This supports
  the strict observed response contract, not a claim that every episode ever
  published appears in the native catalogue. Unknown response/placeholder
  shapes fail closed. Focused Kadocomi tests passed **63 tests**; independent
  Reviewer approved with **0 blockers**.
- **F2.6 — preserve positions and history for absent Sources:** review found
  that replacing a complete inventory cleared positions of all existing
  Sources before applying observed rows. Position writes now affect observed
  identities only. An existing Source absent from the inventory keeps its
  prior position and history, while Scope Reconciler still blocks with
  `missing_listing`; a retained old position is not proof of membership. The
  Catalog / Discovery / Scope / Kadocomi / routed-browser regression passed
  **191 tests, 473 warnings, 0 skipped**. A downstream archive/Batch safety
  regression passed **60 tests, 19 warnings, 0 skipped**. Independent review
  approved with **0 blockers**.
- Root's read-only copy harness verified both Kadocomi works on isolated
  Catalog copies: pre-existing Source IDs, Item states and CrawlRun/Artifact/
  quota history digests were preserved; native positions and availability
  matched the observed lists; Scope preview was ready. The primary work's
  Batch plan had zero candidates because its observed Sources were already
  completed. The secondary work was checked for native ordering and scope
  flags, but no Batch plan was run for it. These are not execution-success
  claims. No capture, paid access, ticket/quota action, or operational Catalog
  write occurred. Reports:
  `output/acquisition-site-followup/kadocomi-copy-live-report.json` and
  `output/acquisition-site-followup/kadocomi-second-copy-live-report.json`.
- Current complete-listing inventory and bounded Discovery coverage is eleven
  adapters: Zeblack, BookWalker, Magapoke, Jump+, MANGA ONE, Piccoma, Hanayume,
  Younganimal, ComicFUZ, Kadocomi, and Comic DAYS. Kadocomi remains opt-in for
  scoped/ordered targets; missing native IDs and unobserved leading/all-inactive
  placeholder patterns cannot be inferred. Comic DAYS now supports bounded
  `discovery_scope`.
- Root completed the final full repository suite after F2.6. The exact result
  and both failures are recorded below. The earlier 4,946-pass / 1 user-config
  failure result below is a pre-adapter-follow-up run and remains historical.

### Final verification and audit history

The first full-suite attempt was stopped after 313 tests / 579.6 seconds when
the ComicFuz browser stage showed no progress for roughly six minutes. The
partial log records 295 passes and 18 failures, all from integration fixtures
that had not yet supplied/reapplied the newly required Watchlist scope sync;
there is no final teardown/summary, so the run is archived as interrupted and
not treated as a completed suite. The two adjacent ComicFuz browser nodes
passed when run alone (2 passed in 3.69 seconds, with a 120-second bound and
faulthandler diagnostics); evidence is in
`output/work-key-archive-order-p5/comicfuz-bounded-diagnostic.log` and
`comicfuz-bounded-result.json`.

The full integration run exposed stale test setup that had not explicitly
reconciled Watchlists after Full Discovery. The affected integration fixtures
were updated to create or reuse an isolated Watchlist, assert the unsynced
Batch rejection where relevant, apply `ScopeReconciler`, and pass the same
Watchlist / isolated library path through Planner and Executor. In particular,
the ComicFuz discovery-to-batch-rerun case now proves that a successful Full
Discovery invalidates scope synchronization: its first replan is rejected,
then the existing Watchlist is explicitly reconciled before replan. These are
test-fixture corrections; production gates and access behavior were not
weakened. Static AST parsing passed for the corrected ComicFuz module. The
final full `pytest -vv` run with faulthandler diagnostics completed after these
fixture corrections.

The final full suite after the Comic DAYS and subsequent adapter/history-safety
follow-ups completed with **4,991 passed, 2 failed, 0 skipped, and 5,340 warnings**
in 2,499.04 seconds (41:39). The first failure was
`tests/integration/test_piccoma_adapter_browser.py::test_piccoma_transition_waits_in_frame_and_preserves_failure_diagnostics[764-1200-700]`:
it raised `UnknownPageStateError` because body canvas geometry did not stabilize
within the test's 1,200 ms timeout (elapsed 1,422 ms). The exact parameter passed
alone (**1 passed, 5 warnings, 4.04 seconds**) and all 12 parameters in that timing
matrix passed on recheck (**12 passed, 5 warnings, 0 skipped, 40.49 seconds**).
The timing failure did not reproduce, but its cause is undetermined; this remains
a full-suite failure. The Piccoma test was outside the Catalog/Discovery/Scope
code path and no related source or test changes were made. Evidence is in
`output/acquisition-site-followup/full-pytest.xml`, `full-pytest.log`, and
`piccoma-transition-matrix-recheck.xml`.

The second failure was the existing
`tests/unit/test_runtime_settings.py::test_distributed_crawler_yaml_resolves_piccoma_settings_without_changing_other_sites`:
it expected the tracked baseline BookWalker `page_turn_delay_ms` value of 200 but
read 0 from the user's existing, unmodified `crawler.yaml`. Root reran the exact
unchanged test file against an isolated copy of the tracked baseline config:
**1 passed, 1 warning, 0.14 seconds**. Independent Reviewer confirmed the tracked
baseline value is 200 ms, the user's current setting is 0 ms, and neither runtime
source nor the test has a diff. The user's config was not edited. This remains an
environment-dependent failure, not a code regression.

Before these adapter/history-safety follow-ups, the shared P0-P5 implementation
full suite had **4,946 passed, 1 failed, 0 skipped, and 5,205 warnings** in
2,480.96 seconds. Its sole failure was the same runtime-settings test described
above. The exact unchanged test file passed against an isolated copy of the
tracked baseline config (**1 passed in 0.09 seconds**). That earlier run remains
historical and is not substituted for the final full-suite result.

The user's `crawler.yaml` remained unmodified throughout; its before/after hash
was verified unchanged. The final test run did not alter
source or test files. Documentation changed during the run, so a raw all-file
hash comparison is not claimed.

The final lint command, `.venv/Scripts/python.exe -m ruff check src tests
scripts/renumber_archives.py`, passed with **All checks passed**. There were no
skipped tests. The full run took about 41 minutes. The earlier interrupted run
and its fixture failures remain documented above for audit history.

Independent review approved the documentation and copy-only verification. The final full-suite
result has two recorded failures; the isolated reruns support the user-config attribution for one,
while the Piccoma timing failure remains unexplained. No code or test changes were requested.
The phase is complete for isolated-copy verification. It does not
mean production migration, scope apply, or renumber has been performed.

The Kadocomi follow-up used only bounded metadata reads of two public work
pages, then copy-only Catalog validation. No paid entitlement, reader/capture,
ticket/quota action, or operational Catalog/output mutation was performed.
Production migration, scope apply, and renumber remain explicit operator steps
documented in the runbook.

## Update contract

After each phase record: commit/ref, files touched, design deviations, test command/results,
skipped/failed tests and reasons, integration/live verification limits, reviewer findings,
and the next blocking issue. Do not label planning as implemented.
