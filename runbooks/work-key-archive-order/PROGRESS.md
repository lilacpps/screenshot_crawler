# Work-key acquisition scope / archive ordering — Progress

> Status: **IN PROGRESS** (2026-10-22)
> Main runbook: [README.md](README.md)
> Branch: `feature/work-key-archive-order`. P0-P3 are complete and independently reviewed; P4 is next.
> No live site, normal Catalog, Watchlist or Books output has been used.

## Phase gates

| Phase | Status | Evidence / next action |
|---|---|---|
| P0: Current contract / fixture | COMPLETE | Existing call paths reviewed; isolated synthetic fixture and baseline tests recorded below |
| P1: Watchlist + Catalog v7 | COMPLETE | implementation, focused tests and independent Reviewer APPROVE; see P1 record below |
| P2: Scope reconciler | COMPLETE | read-only dry-run, CAS apply, evidence gates, orphan handling; independent Reviewer APPROVE / BLOCKING 0 |
| P3: Batch integration | COMPLETE | normal/grant-only/deferred/replan filtering and consistency gate; 434 affected tests pass; independent Reviewer APPROVE / BLOCKING 0 |
| P4: Naming + renumber | NOT STARTED | work-key cross-site numbering and ZIP/status/Artifact transaction checks |
| P5: Verification + rollout | NOT STARTED | isolated full test, selected-work dry-run, backup, docs/note sync |

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
- Site-native complete-inventory hooks are wired for Zeblack, BookWalker,
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

Next: receive final P3 Reviewer approval, then implement the P4 shared opt-in
archive-position plan and work-wide safe renumbering. P4 must also preserve
legacy no-order behavior and reject existing archive/status/hash drift before
any selected work-wide apply.

## Update contract

After each phase record: commit/ref, files touched, design deviations, test command/results,
skipped/failed tests and reasons, integration/live verification limits, reviewer findings,
and the next blocking issue. Do not label planning as implemented.
