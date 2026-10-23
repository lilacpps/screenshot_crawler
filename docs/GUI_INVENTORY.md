# Windows Inventory GUI (P0 / P1)

P1 is a local, read-only PySide6 application. P2 execution is out of scope.

## Data contract (P0)

`CatalogInventoryReader` validates v7, then bulk reads one SQLite `mode=ro`,
`query_only=ON`, `BEGIN` transaction. It never constructs a writable Catalog
service. A missing database or Watchlist is an error. Latest CrawlRun per Item
and latest Artifact per Item/kind/format/backend are read in the same snapshot;
older run history is deliberately not loaded. No archive filesystem inspection.

Strict non-mutation includes SQLite sidecars. WAL databases are rejected before
SQLite opens: mode=ro may still update shared-memory read marks (observed hash
change with unchanged mtime). P1 neither checkpoints nor changes journal mode.
Use an operator-created consistent rollback-journal backup. `immutable=1` is
not used because it would ignore committed WAL pages. This is an explicit safe
limitation discovered during P1 review, rather than a falsely read-only promise.

`InventoryService` has no Qt imports. Frozen DTOs and read-only mapping indexes
hold Work, Item, Source, target, scope evidence, resource state and recent history.
One aware JST `now` is used per reload. `KeyInventory` retains Watchlist identity,
scope, enabled-for-discovery and archive_order. Synthetic, unselectable unmanaged
groups retain Catalog-only Sources without inventing Watchlist identities.

Counts use unique Item IDs with at least one assigned Source in that group:

`total_assigned = completed + external + skipped + direct + quota + paid + unavailable + unknown`

Out-of-scope counts count Sources, not Items, and are excluded from this equality.
Completed means Crawler completed only. Cross-site content is never merged.
Multiple assigned Sources with conflicting classifications produce unknown plus
a diagnostic. Repeated membership across keys is diagnosed; parent totals are
recomputed from the union, never summed blindly. Missing/undiscovered keys make
aggregate totals partial (display —); stored observations remain in details.

| Input | Classification |
|---|---|
| Item completed / external / skipped | respective distinct category |
| pending, Policy eligible direct | direct |
| pending, Policy eligible quota with quota_available=None | quota pool |
| Policy paid / expired_rental | paid |
| Policy unavailable / expired_free | unavailable |
| unsupported, Policy exception, ambiguous | unknown + reason |

The Policy owns expiry/grant semantics, including cases where a free_until field
is not used by that site's existing policy. The GUI does not invent expiry rules.
An expired paid rental is paid; an active rental is direct only if Policy says so.
Site quota slots use all Sources of that site once and are separate from the
quota pool. Named resources are metadata, never additional Item counts.
Grant retry timestamps use Policy APIs and runtime configuration only; absent
API support or absent consumed-state evidence remains unknown.

Scope uses the existing ScopeReconciler over an indexed, read-only in-memory
facade. Its real binding/evidence/digest/position/flag checks remain authoritative;
no apply, Catalog write, archive stat or per-Work DB query is needed. Ordered
archive positions use the existing pure archive-order planner only after scope
has been proved. Last full proof and last access observation have separate labels.

The facade exposes only `read_acquisition_scope_snapshot`,
`read_works_items_sources_and_targets`, `read_work_archive_artifacts` and frozen
Watchlist `list_targets`; the first two return indexed memory, the last Catalog
method returns no archives. It has no connection, job_lock or apply capability.
P1 does not verify physical archive existence or preview renaming. Scope states
include synced/stale/missing_work/not_discovered/unmanaged/binding_mismatch/error;
missing proof and invalid position/digest are stale with the exact blocker reason.
`out_of_scope` always means out-of-scope Source count in the DTO and UI.

Policy evidence reviewed: BookWalker owned/direct and quota/site slot; Manga ONE
free/owned/direct, active quota grant/direct and quota/site slots; Magapoke
quota/work_ticket with premium_ticket metadata; Zeblack, Hanayume, Comic DAYS,
YoungAnimal free/direct and quota/work ticket; YoungAnimal and Jump+ active paid
rental/direct; Piccoma active manual quota grant/direct, other quota/unknown;
Kadocomi valid unexpired free/direct, expired free/unavailable; ComicFUZ free/direct
and paid/paid. All eleven reject unavailable; unsupported modes stay unknown.
The existing registry membership is tested against CLI to detect registration drift.

## UI contract

1400×850 main window; path controls and reload above view/search/filter toolbar;
QSplitter holds a QTreeView (about 70%) and detail pane. Site → Work → key and
Work → site → key project the same snapshot. Detail includes full Work/site/key
membership, source rows and recent Item history. Item rows use a Qt table model.

Checked keys are a stable set of actual Watchlist keys, independent of focused
detail. Parents act on all descendant keys, including hidden ones; partial
selection has Qt's intermediate state. View/filter/sort never change this set.
Reload intersects it with current keys and reports removals. Disabled discovery
keys remain selectable and visibly disabled for Discovery. Unmanaged groups
cannot become execution targets. Search matches title, label, key and site;
matching descendants retain ancestors. Sorting is among siblings, numeric for
counts; unsorted key order uses archive_order or Watchlist file order.

Loading and all Policy/Scope calculations run on a worker. Snapshot replacement
is atomic on the GUI thread. A failed reload keeps an explicitly stale display.
No GUI settings persistence; no jobs, process launch, network, CDP or execution.

## Verification contract

Inventory classification matrix across existing policies; duplicate Sources and
membership; stale/missing/mismatched scope and evidence; undiscovered/unmanaged;
missing/old/corrupt DB and invalid Watchlist; immutable snapshot and read-only
hash/mtime proof. Qt offscreen tests cover projections, tri-state, hidden keys,
focus, numeric sort, reload/error and disabled actions. Windows sample screenshots
cover site/work/Work detail/Item detail. A 1,000-key/100,000-Source fixture measures
load, model projection and search. CLI must work when Qt imports are blocked.

Affected Catalog/Watchlist/Scope/Policy/CLI tests run; browser, live and Research
are unnecessary because P1 never opens a browser or external site.
