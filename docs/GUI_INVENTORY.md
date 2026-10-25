# Windows Inventory GUI (P0 / P1 / P2 / P3)

P1 is a local PySide6 application. P2 selected execution uses a read-only
preview and a separate Catalog-locked worker. P3 persists queue state in a
separate management SQLite database and never auto-resumes unfinished jobs.

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
| Policy pending_quota=true, ineligible | quota pool (inventory only) |
| unsupported, Policy exception, ambiguous | unknown + reason |

The Policy owns expiry/grant semantics, including cases where a free_until field
is not used by that site's existing policy. The GUI does not invent expiry rules.
An expired paid rental is paid; an active rental is direct only if Policy says so.
Site quota slots use all Sources of that site once and are separate from the
quota pool. Named resources are metadata, never additional Item counts.
`PolicyDecision.pending_quota` defaults to false. A site policy can explicitly
identify known, non-executable quota inventory with this flag; it changes no
Batch eligibility, strategy or resource support. Paid/unavailable decisions
retain precedence. Piccoma uses it for available quota sources awaiting manual
unlock, including 待てば¥0, ¥0＋ and 爆読み. No site-name or badge rules are
embedded in the shared inventory projection.
Grant retry timestamps use Policy APIs and runtime configuration only; absent
API support or absent consumed-state evidence remains unknown.

Normal inventory uses saved acquisition flags and per-key ordering directly.
The old work-wide sync marker is maintenance history, not a GUI/Batch gate.
Existing listing fingerprints and saved bindings can reveal pending range edits;
known deleted keys show explicit scope-sync as the needed action. These warnings
are key-local and do not prevent using saved flags. Invalid ownership remains
blocking. Proof freshness, position changes and archive_order alone never cause
an acquisition warning. No schema, JSON field, per-key sync record or digest is added.

Archive positions use the same provisional pure numbering plan as Batch. Keys are
ordered by archive_order, their enabled Sources by existing display_position;
missing/duplicate positions retain deterministic Batch fallback. Intermediate
numbering need not be final. Operators can renumber once after acquisition, without
first applying scope-sync or obtaining fresh complete listing proof. Actual file
and identity safety checks remain in maintenance. GUI never stats/renames ZIPs.
Read-only/single-snapshot and no-SQLite-sidecar-mutation contracts are unchanged.

Policy evidence reviewed: BookWalker owned/direct and quota/site slot; Manga ONE
free/owned/direct, active quota grant/direct and quota/site slots; Magapoke
quota/work_ticket with premium_ticket metadata; Zeblack, Hanayume, Comic DAYS,
YoungAnimal free/direct and quota/work ticket; YoungAnimal and Jump+ active paid
rental/direct; Piccoma active manual quota grant/direct, pending quota/quota pool;
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
The Jobs page is a separate history view; process launch, network, CDP and
Catalog writes remain in the confirmed worker subprocess.

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

## Execution history monitor integration

The Jobs history view is an observer of the same management store and
controller used by the main window. Its embedded monitor reuses the bounded
log tail and immutable result Presenter. The list retains the selected
`job_id` and viewport across unchanged refreshes; details retain a manual
scroll position when content changes. Latest events are read with a descending
bounded SQL query and displayed chronologically, avoiding the old first-500
window.

The queue supervisor owns all execution and safety decisions. Monitor or
history initialization and refresh errors are isolated from queue advancement,
while controller/database failures remain fail-closed. This GUI behavior is
validated with synthetic jobs and offscreen/native Windows captures only.


Phase 04 live-monitor evidence uses only synthetic management jobs. The lower
monitor and Jobs history share the existing controller/store, preserve their
independent selections and scroll positions, and expose bounded raw logs plus
structured summaries/problems for all three actions. Native screenshots and
`gui-screenshots/phase4-live-monitor.actual.json` are the current visual
record; empty-monitor captures from earlier phases are historical diagnostics.
