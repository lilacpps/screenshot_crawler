## Bounded non-consuming resolver preparation (2026-10-29)

`SiteAdapter.configure_access_resource_resolution()` optionally receives the
original observation timeout, resolved runtime page-turn delay and the current
Works' explicit Watchlist exclusion IDs. It returns a positive integer total
operation budget; invalid values stop before Guard/network setup. Defaults
retain the original resolver budget. Duck-typed integrations without the hook
retain the old behavior. The Executor uses the returned budget plus its existing
2-second allowance while preserving AccessGuard racing, cancellation, cleanup,
same-Page prepared entry and existing consumption persistence.

Zeblack opts in to 180 seconds for a conditional predecessor reread; its site
module owns all stock/eligibility/reader selectors and limits. Core/Batch contains
no site/resource branch, URL or consumption rule for that feature. Resolver
preparation does not create a CrawlRun, content files, Artifact, completion or
quota/cooldown state. Existing real request events remain observable. Default
Runner capture pacing and non-participating sites are unchanged. No schema,
CLI or YAML setting was added. See note/06_zeblack.md for the site behavior,
synthetic coverage and isolated non-consuming production live verification.

Final affected verification: shared Executor/CLI/deferred grant **252 passed**
and Zeblack Unit/browser Integration **218 passed**, with **0 skipped** overall.
Ruff and diff checks passed. The whole 5,924-case suite was attempted and
interrupted during unrelated browser coverage because of its runtime; no
full-suite success is claimed. Research helpers were unchanged. Live verification
covered stock-confirmed restoration and the final prepared-document handoff,
without consuming a real ticket or updating operational Catalog state.

## Comic DAYS initial dummy/front page (2026-10-28)

Comic DAYS item 22405's site-local `dummy-front-double` normalization now skips
one positively identified non-body prefix using the ordinary forward control,
then requires the two first body canvases at slider 2. Access and shared Runner
timeouts/capture/output remain unchanged. Read-only live traversal reached the
22 body areas and END without consuming rights or writing operational output;
see note/08_comicdays.md for structure, evidence, tests and limitations.
Comic DAYS affected group: 218 passed; final prefix/normalization browser group:
27 passed, zero skipped. Ruff/diff checks and independent review passed. Full
pytest/Research and operational Batch download were not rerun for this site-local
correction; current live initialization and metadata-only END traversal passed.

## Work-level registration, scope replacement and segment ordering (2026-10-27)

The toolbar's `新規登録・範囲・置換` opens WorkEditorDialog. The existing
Watchlist管理 key editor remains available for basic fields and Magapoke's
checkbox workflow. WorkDraft holds unsaved registration and all key proposals
for a Work, keyed by explicit site/key identities. New Works and additional
sites can fetch read-only complete listings before saving or running Discovery;
no temporary Work/Source is created. The new editor requires an existing valid
Catalog v7, read through the same sidecar-safe CatalogInventoryReader.

The Work editor's search box offers case-insensitive substring completion over
Work labels and work_key values, including unsaved new Works. Selecting a result
uses the existing Work switch and unsaved-change confirmation; typing alone
does not alter the current draft or write settings. The selected Work remains
visible in the separate combo. Search is disabled with other edit controls
during an editor task or background job.
Enter without a visible completion popup does not invoke the dialog's Add
button. Search, keyboard selection, unsaved-change confirmation and adjacent GUI
regressions passed (70 tests, zero skipped), with targeted ruff/diff checks and
independent review also passing. Full suite, browser-backed Integration,
Research and live verification were not rerun for this local GUI addition.

Site lists display oldest-first labels/status and current/proposed assignment.
Comic DAYS now supports complete-list preview and exclusion scopes as well as
Magapoke, Jump+ and Zeblack. Its existing verified Atom/free-feed/pagination/access
reader is shared with Discovery. Page/target-bound exclusion proof is replayed
once within 30 seconds and stale/missing/mismatched proof fails before any row.
The Magapoke-to-Comic DAYS Planetes workflow replaces only the two selected native
rows, leaving the final Magapoke row and its state independent; see site note 08.
Related Comic DAYS/listing/GUI and artificial-browser tests passed 202 cases with
no skips on a short OS TEMP base; the final isolated replacement E2E also passed
after cleanup. Read-only live previews returned 26 Magapoke and 27 Comic DAYS
Planetes rows, without applying the user's operational draft or consuming rights.
Full suite and Research were not rerun for this site-local addition.
Jump+ complete-list validation uses UI range slot counts and native identities;
it does not equate range numbers with chapter titles (offsets and split titles
are valid). A failed listing still stops editing; see note/04_jumpplus.md for
the Exorcist live observation and adapter-specific checks.
The site-local correction passed 44 Discovery/artificial-browser and 108 adjacent
listing/GUI/Jump+ tests (zero skipped), plus independent review; read-only live
previews succeeded for Jump+ (129 rows) and Zeblack (117 rows). No operational
Watchlist/Catalog/ZIP was changed. Full suite and Research were not rerun.
Interval controls support fixed bounds, oldest-open and newest-open selection;
newest-open is the default for a continuing tail. The translation to Discovery's
newest-first URL boundaries is explicit. A replacement selects a contiguous
source interval and a destination interval (including an unsaved new target),
removes source selection, inserts destination at that location and splits the
remaining source sequence. Repeated replacements and unequal counts are valid.
Native identities, Source ownership, Item completion and files never transfer.

Background jobs owned by MainWindow disable editing but do not prevent closing
the Work editor with the window close button or Escape. Closing leaves the job
running and retains the existing unsaved-change Discard/Cancel confirmation.
Only the editor's own listing, preview or save task blocks closing until its
callback finishes; edit and close guards intentionally use different conditions.
The close regression covers window close/Escape, clean/Discard/Cancel states,
unchanged Watchlist/Catalog bytes and own-task protection: 17 Work editor tests
and 46 adjacent GUI tests passed (zero skipped); targeted ruff and diff checks
passed. Independent review found no blockers. This dialog-only fix does not
require a new full suite, browser-backed Integration, Research or live-site run.

WatchlistTarget.archive_segments is optional tuple[ArchiveSegment, ...]. Each
segment has a positive Work-unique order and optional oldest-first inclusive
start_external_id/end_external_id. Omitted bounds are open. Every Work key
specifies segments or none does; archive_order and segments cannot mix. An empty
tuple (YAML []) denotes zero assigned rows, using an explicit exclusion scope.
The shared archive plan orders segments, then enabled rows by display_position;
enabled rows must appear exactly once and unresolved/disabled anchors, overlap
or unplaced enabled rows fail that Work's numbering. A nonempty segment without
enabled known Sources also stops numbering (a new site must first be discovered);
an explicit empty segment tuple remains valid for a fully excluded key.
Legacy provisional fallback
is retained for Works without segments. Audit/renumber recognize segment mode.

Service parsing, lossless block-YAML patching, update operations and saved JSON
restoration preserve segments. Ordering fingerprints/configuration JSON include
them; site scope fingerprints/acquisition bindings do not. DB stays v7 with no
new columns/tables; this optional configuration-JSON extension supersedes older
"no new JSON fields" wording for segment layout only.

Lossless YAML field insertion appends immediately after the target's existing
data, before separator blank lines and the following Work's heading. Newly
added scope and ordering fields use scope-then-order/segments order. Field
replacement/removal leaves peer-level trailing comments and separator lines
outside its span; deeper nested comments still block scope/segment replacement.
Target spans also stop before unrelated root fields. Original LF/CRLF, comment
text and unrelated fields remain intact; this is a local patch, not a whole-file
formatter. YAML syntax/target equality and CAS validation still precede replace.
Watchlist/WorkDraft/GUI regression coverage includes exact LF/CRLF output,
following Work headings/root footer, EOF without a newline, simultaneous
scope/order or scope/segments additions, nested annotations, and scope
replacement/removal. The reported three youchien-wars entries were locally
reformatted under the Watchlist edit lock with whole-document parsed-value
equality verified before and after; no setting values, Catalog or ZIP changed.
Formatting regression run: 128 passed, zero skipped; targeted ruff, diff checks
and independent review passed. Full suite, browser-backed Integration, Research
and live verification were not rerun for this YAML text-patching-only change.

Work preview validates all fresh complete lists (300 seconds), exact scope and
sequence coverage, Watchlist revision and one read-only Catalog snapshot. Same-site
overlap, unknown/unbound Source ownership and active Sources absent from their
owner's complete listing fail closed. Missing Catalog Work,
Items/Sources or final archive names alone do not prevent saving. Counts/order
are listed as pending Full; existing archive references are reported without
filesystem access. The legacy artifact-bound key editor remains stricter.
Save revalidates under Catalog job lock and atomically replaces only Watchlist
under CAS. Catalog, history, quota and ZIP bytes remain untouched.

Save emits explicit added/scope/URL-changed keys plus all ordering-affected Work
keys and saved revision. MainWindow reloads (deferring another read when one is
already in flight) and offers a single Full Yes/No confirmation with the existing
execution preview. Yes queues the existing worker; No only saves. Inventory
execution checks remain unchanged. Changed inputs are rejected by revision and
worker fingerprint checks, disabled keys stay disabled, failures never auto-retry.
Normal Full reflects per-key flags; no implicit Scope apply occurs. Pending outer
boundary edits use old flags; saved exact holes use the existing Batch deny.
Existing ZIPs require explicit audit/renumber if desired; physical DB cleanup
and automatic file replacement remain outside this feature.

Validation: synthetic WorkDraft/Qt tests cover fresh Works, existing+new sites,
post-registration replacement, single/multiple/unequal replacement counts,
no-Catalog-write save, synthetic Full and shared numbering/Batch integration,
stale snapshot/CAS, and one-confirmation Yes/No flow. Final validation:

- Latest WorkDraft/Qt/synthetic listing-browser group: 18 passed.
- Adapter unit + artificial browser listing group: 74 passed.
- Core/Watchlist/Archive/Inventory/Scope regression group: 204 passed.
- Latest nonempty/empty segment and disabled-position guards: 5 passed.
- Independent read-only review: PASS, zero blocking findings after corrections.
- Full pytest: 5805 passed, 3 failed, 0 skipped in 3254.61 seconds (5884 warnings).
  One unchanged Comic DAYS DOM snapshot test timed out; two Hanayume tests
  exceeded Windows path limits in the long workspace-local basetemp. All three
  passed together via --lf with a new short basetemp under the OS TEMP directory
  (3 passed, 9 warnings). The one-shot full run is not described as green.
  Final narrow proof/segment guards added during the broad run were separately
  checked with current code in the targeted groups above.
- `ruff check src tests` and `git diff --check`: passed.
- Synthetic Qt captures verified 1400x1000 and 980x700 logical sizes; a native
  Windows capture at DPR 1.5 verified the larger layout. No real-site page images
  were used as fixtures or screenshots.

No operational Watchlist or Catalog
has been edited by verification. Site live evidence belongs to the site notes.

## Policy-owned pending quota inventory (2026-10-25)

`PolicyDecision.pending_quota` is an optional in-memory bool (default false)
for known quota inventory whose acquisition is unsupported or unavailable to
the executor. Inventory maps it to Quota対象残 after the existing eligible,
paid and unavailable branches. It never changes eligibility, access strategy,
resource support, quota consumption or Batch selection. Completed/external/
skipped Item status and ambiguity handling retain precedence; exceptions remain
unknown. Site-specific rules stay in SitePolicy; no shared site-name branch,
Catalog schema, persistence field, CLI/config or runtime access change is added.
Piccoma opts in only for available quota sources without an active manual grant;
active manual grants remain non-consuming direct. Other policies retain false.
See `note/09_piccoma.md` for observed badge sets and live verification. Ordinary
GUI reload applies the policy projection; newly recognized badges need Discover
to refresh stored access_mode. No operational Catalog/config/library is changed
by validation.

The cross-site Policy classification matrix and synthetic inventory invariants
pass with the default flag preserving other policies. Piccoma's synthetic
Discovery-to-Catalog-to-GUI/Planner tests verify quota counts without an
executable quota candidate or resource. Targeted validation and shared-CDP
read-only/copy evidence are detailed in `note/09_piccoma.md`.
An initially over-broad full-suite attempt was stopped before completion; no
full-suite pass is claimed for this bounded default-false display extension.

## Watchlist scope editor Stage 01 (2026-10-25)

The Watchlist model now accepts DiscoveryScope.excluded_external_ids as canonical, sorted site-native external ID strings. A scope containing only exclusions is valid; an empty exclusion list is omitted. Duplicate, empty, and non-string IDs fail closed. Scope and work fingerprints plus persisted configuration JSON include the canonical exclusion list, and saved configuration restoration rejects malformed boundaries or duplicate exclusions.

WatchlistService provides read-only revision/preview support, update_target, and work-atomic update_work_archive_order. Mutations use a per-Watchlist path lock, revision compare-and-swap, durable temporary-file flush, and atomic replace. Ordinary block YAML edits patch source spans so unrelated comments, root keys, and target keys survive; ambiguous flow/multiline or nested-scope-comment cases fail without writing. These APIs do not write Catalog, ZIP, or scope-sync state. Stage 03 now provides the narrow Batch safety overlay for newly saved exclusions; outer-boundary edits still carry the GUI Full/Apply warning until scope reflection.

Validation status: Watchlist unit tests cover legacy/boundary/exclusion forms, canonicalization, comment and unknown-key preservation, preview no-write, CAS/concurrency, archive ordering, and fail-closed syntax. No live-site or operational data verification was performed.

## Watchlist GUI scope editor Stage 04 (2026-10-25)

The Windows GUI now opens an independent WatchlistEditorPage from the
existing MainWindow toolbar. Its read-only Watchlist summary and selected-key form edit label, enabled, URL, scope, and all keys in a Work's archive order while its complete listing checkbox model remains separate from Inventory execution selection. Label/enabled-only edits remain usable without a listing capability; URL, scope, and archive-order changes require a fresh complete listing and Catalog-bound preview.
The editor includes the existing hierarchical InventoryTreeModel projection
with search/status filtering, while its Watchlist and episode checkbox models
remain independent from execution selection. The listing button checks adapter
capability before connecting to CDP, then uses the shared endpoint in a worker
and delegates the catalog-free ListingPreviewService; adapter-owned navigation
performs the site read. The GUI never performs a generic target navigation.
Unsupported sites remain Catalog-reference only and cannot commit a checkbox
scope. Synthetic listings can be injected with `set_listing(listing,
checked=...)` for offscreen tests.

Preview is read-only and binds the current Watchlist revision/path pair and
one immutable CatalogInventoryReader snapshot. Save requires a fresh
ScopeEditPreview for every selection-affecting draft and calls the
single-lock/CAS `WatchlistService.apply_edit` operation, so basic fields, scope,
and Work archive order cannot be partially written. The worker re-reads the
Catalog inside the Catalog job lock, compares its content identity and the
preview's target token/age, and rejects changed or ambiguous source/run/artifact
joins. `Scope preview` and `Scope apply` run in workers; apply reuses the Catalog
job lock and reconciliation revision CAS. Full Discovery sends the editor's
explicit key to the existing execution preview without altering the Inventory
check set. Dirty editors, changed paths, active jobs, stale listings, empty
checkbox selections, unsupported scope capability, sibling overlap, and
unresolved ownership stop safely. Existing CRLF Watchlists retain their raw
line endings and byte-based revision hash. No live-site or operational data
verification was performed.

The saved target tuple remains the baseline while reordering/adding modifies only
the draft. Discard restores the full saved tuple; cancel restores the selected key.
A standalone reload reads Inventory asynchronously and updates the shared tree;
MainWindow refresh invalidates both edit and Scope-sync previews, including any
in-flight preview result. Obsolete apply completion triggers a fresh read because the mutation may already have committed; it never labels an older snapshot as current.
Controls are disabled during jobs/workers, and closing/rebinding waits for active
editor operations. Reopening creates a fresh editor. The Work comparison combines
complete-list and Catalog-only rows while only the active key's complete-list rows
are checkable. Position range selection and a scrollable editing area support large lists and small Windows sizes.
The listing worker closes its CDP session even if page creation fails. Unsupported
capabilities are rejected before CDP connection.

The isolated Qt/Catalog E2E covers no-write preview, atomic hole save, synthetic Full
through DiscoveryService, stale Scope apply rejection/retry, final Batch selection,
and unchanged bytes of an existing valid ZIP. Other regressions cover same-size/
same-mtime Catalog changes and new CrawlRuns, Watchlist CAS, same-site overlap before
Catalog registration, one-sided boundaries, snapshot/worker races, active jobs and
new-key Full without changing execution checks. Native Windows captures use synthetic
1,000-row inputs at logical 980x700 and 1400x1000, DPR 1.5. No real site or CDP account
was used for verification.

The 2026-10-25 UX follow-up defaults navigation to Work / Site / Key, filters the
key summary to that Work, and adds a vertical splitter so the navigation can grow.
The lower WorkEpisodeModel shows all sites/keys of the same Work with independent
identity, status, title origin and unknown placeholders. It never merges same-ID
episodes across sites or keys. Siblings are read-only; their context action switches
the active editor through the existing dirty guard. Checkbox changes update cells
without resetting scroll; structural changes focus the active key.

Catalog chapter text uses Item.order_label before item_title, fixing blank/misleading
titles where Discovery already retained a native episode label. Read-only listing
previews supply temporary display_title for all rows, including non-Catalog rows.
The per-key memory cache is bound to site/key/URL and retains observation time for
existing freshness gates. No schema or Discovery persistence change is made.
The listing button reads all keys of the current Work sequentially; unsupported
capabilities stop before CDP and keep Catalog references. Full first runs this same
no-write listing flow, then emits only its explicit key to the existing execution
confirmation. Canceling confirmation leaves temporary names visible. Active jobs,
dirty edits or Watchlist revision changes prevent an unsafe continuation. Discovery
and capture execution semantics are otherwise unchanged.

The episode context menu copies URLs or assigns from_url / through_url for the
active key. It resolves site/key/external ID/URL again after its nested event loop,
so a moved row cannot assign another episode. Explicit boundaries replace an
unsaved checkbox proposal, preserve saved holes, support one-sided intervals and
reject reversed/missing boundaries. They still require the same preview/CAS before
save. Tests and native captures use isolated synthetic data; no new live-site claim
is made. The comparison module and editor tests cover these UX boundaries.

## Read-only complete listing preview Stage 02 (2026-10-25)

The shared Discovery layer defines ListingRow and ListingPreview DTOs plus a stable digest over listing identity, ordered site-native external IDs, and authoritative positions. DiscoveryService.preview_complete_listing delegates only to an adapter optional capability; unsupported sites and incomplete adapters return visible blockers. The method does not acquire Catalog job locks, call normal Discovery synchronization, or write Catalog, Watchlist, ZIP, or management state.

Magapoke implements the capability by reusing its existing complete episode-list expansion and parsing helpers. This Stage does not add GUI behavior or scope application. Synthetic Chromium and unit validation cover complete rows, canonical IDs/positions, digest behavior, unsupported-site blockers, and zero operational files. No live-site or paid-resource verification was performed.

## Watchlist scope selection and exclusion safety Stage 03 (2026-10-25)

`SelectionPlanner` maps a non-empty checked set from a complete listing to an
inclusive `DiscoveryScope` boundary plus sorted inner
`excluded_external_ids`. It validates listing identity, digest, unique IDs,
positions, URLs, and checked IDs before producing a proposal. `ScopeEditPreview`
joins that pure proposal to a caller-provided read-only Catalog snapshot and
reports each row as keep/enable/exclude/add/owner-conflict, including unknown
new rows. The preview binds listing identity/digest, Watchlist revision and
content SHA, Catalog snapshot identity, and observation time in a token; it
does not open Catalog or write any state. Archive numbering uses the existing
pure work-wide planner when a complete snapshot is supplied. Before/after
number changes are shown only when current archive positions and an immutable
source-joined snapshot of existing artifact/collision facts are supplied by a
read-only caller. Expected artifact stems are generated with the shared
`catalog_archive_stem` naming primitive, including hyphenated title/order/
author components; duplicate joins, unknown Sources, colliding locators,
missing positions, and incomplete facts remain explicit UNKNOWN blockers.

Discovery exclusion runs are fail-closed before the Work is created or any
Source is upserted. The adapter must opt into exclusion support and replay the
same complete listing that was used for the preflight. Core checks target
identity, row identity, digest, duplicate IDs/positions/URLs, boundary order,
and that every excluded ID lies inside the base interval. Magapoke replays its
validated complete episode parse, bound to the Page identity, full target,
scope, and a short TTL, then filters exclusions before Catalog
upsert and writes false acquisition flags only for known same-key excluded
Sources. Unknown or out-of-range IDs and unsupported adapters stop visibly.
Outer boundary edits without exclusions retain the established last-Catalog
flag behavior until Full/scope apply.

Batch Planner applies the same exact `(site, discovery_key, external_id)` deny
overlay before Site Policy and quota selection while preserving existing
`acquisition_enabled` flags for all other Sources. Executor candidate
revalidation checks the current Watchlist before reader, resolver, grant, or
capture entry, so a newly excluded candidate cannot consume access resources.
Other keys and their historical Sources remain untouched. Synthetic unit and
Chromium tests cover hole shrink/re-expand, owner conflict, preflight no-write,
Batch/grant protection, and stale candidate rejection; no live-site or paid
resource verification was performed.
## Minimal acquisition and numbering contract (2026-10-24)

Current DB stays v7; no schema/migration is added. Optional archive_segments
extends existing configuration JSON as described in the current Work editor
contract above. Normal GUI,
selected/whole-site Batch, audit and renumber use existing acquisition flags,
per-key display order and Watchlist archive_order or archive_segments. Discovery's existing key-local
flag/position updates remain authoritative. Provisional intermediate ZIP numbers
are accepted; one final explicit renumber can align existing archives. Normal
operations do not require a scope-sync stamp or complete-listing proof. GUI no
longer propagates a work-wide stale checkpoint/proof failure into every key.
Known range edits and removed bindings still show an actionable key-local warning,
while saved flags remain executable. Identity/configuration errors stay blocking.

Listing-proof refresh/expiry and position-only updates do not stale the saved
scope binding. Explicit scope-sync remains for deletion/offline repair and can
handle removal of a Work's last target. Its own strict preview remains separate.
Renumber reads current flags/ordering, retaining Work-wide selection, membership,
CAS/revision, collision, hash/size, sidecar, alias and rollback checks. GUI stays
strictly read-only, including SQLite sidecars. No operational Catalog, archive,
Watchlist or user runtime setting is changed by verification. No new site live or
paid-resource verification is part of this shared simplification.

Validation: the affected Catalog/Discovery/scope/Batch/GUI/maintenance suite plus
Piccoma Discovery and GUI browser integration passed 433 cases. The final selected
CLI/worker/identity checks passed 161; the updated Comic DAYS regression file
passed 55. Ruff (`src tests`) and `git diff --check` pass.

Full-suite coverage was split into disjoint selections after a single-process
ComicFUZ stall; the isolated ComicFUZ module passed all 69 cases. All 5,523 current
node IDs are accounted for, with no uncovered or skipped tests. After reruns and
updating the remaining old Comic DAYS stale assertion, results are 5,522 passed
and one configuration-dependent failure: `test_distributed_crawler_yaml_resolves_piccoma_settings_without_changing_other_sites`
expects BookWalker page-turn delay 200ms, while the operator's existing
`crawler.yaml` sets 0ms. That setting is preserved. The Hanayume long-path failure
passes using a shorter isolated basetemp. Evidence is in `.tmp/simple-part-*.xml`,
`.tmp/simple-fuz-module.xml`, `.tmp/simple-hana-short.xml`,
`.tmp/simple-comicdays-final.xml` and `.tmp/simple_validation_summary.py`.
Local browser integration and local Research tests ran; no real-site, paid-resource
or operational Catalog/ZIP maintenance was performed. Verification used an audit
hook rejecting writes to operational Catalog/configuration/output paths.

## Discovery incomplete reasons (2026-10-24)

`DiscoveryResult.error` is an optional run-local string (default `None`).
`DiscoveryService` preserves the message of a caught `DiscoveryIncompleteError`;
an unsupported bounded adapter reports an explicit scope-support reason. Empty
exception messages use `Discovery incomplete`. Success, disabled targets, counters,
full/incremental completion rules, and Catalog reconciliation remain unchanged.
No schema migration or retry is added. CLI single-key output shows the specific
error with an incomplete heading; `--all`/`--site` show the reason per target and
in the final failure summary, falling back to `Discovery incomplete` when absent.
Other consumers may read the optional field without changing their stop policy.
Tests extend the existing service acquisition/scope and CLI continuation cases.
The affected suite covered specific and absent failure reasons, both Discovery
modes, single-key output and multi-target continuation. Initial validation had
385 passes and four nested Batch path failures; the four passed with a short
Windows basetemp. Both the changed Python files and whole-tree `ruff check src tests`
pass; `git diff --check` reports no whitespace errors.

Full repository run: 5,428 passed, 2 failed, 0 skipped; evidence is
`.tmp/hanayume-minutes-full.xml`. The BookWalker pending-original timing case
passed an isolated rerun (full-run cause unproven). The other case reproduces
the pre-existing user config `bookwalker.page_turn_delay_ms=0` against the
distributed-config expectation of 200; the user setting is retained. Isolated
reruns: 1 passed/1 failed (`.tmp/hanayume-minutes-full-reruns.xml`). Six focused
CLI reason/continuation cases pass with an explicitly isolated Catalog path.

## Windows inventory GUI, execution, and jobs (P2/P3, 2026-10-24)

The main window now includes a `Discovery` ON/OFF column beside `実行対象`
(2026-10-31). Each managed Watchlist key has a delegate-painted switch with
mouse and Space/Select support; parents show enabled/total counts over all
managed descendants, including hidden keys. Catalog-only rows show a dash.
The logical column is appended to retain existing numeric column/sort identities.
Editor Inventory models remain read-only. `enabled` continues to control only
Discovery: OFF keys stay visible and Batch-selectable, and acquisition flags,
numbering, Catalog and ZIP data are unaffected. No Discovery or Full prompt is
triggered. The former main-window read-only label now distinguishes Catalog
viewing from Watchlist editing.

`WatchlistService.read_snapshot()` returns targets and their SHA-256 revision
from one content read; `InventorySnapshot.watchlist_revision` binds the displayed
targets to CAS. Legacy/synthetic snapshots without a revision cannot toggle.
`gui/discovery_toggle.py` contains the switch delegate and a Watchlist-only
QRunnable that uses `update_target(enabled=..., expected_revision=...)` under
the existing per-path lock/atomic replacement. Saves run serially without blocking
the UI. Active/unverified workers, stale/loading/path-mismatched snapshots,
dirty/busy editors and pending saves reject toggles. During save/refresh, editors,
path changes, close and GUI starts (main/history/automatic dispatch) are blocked.
Clean editors rebase their saved targets/revision and discard old previews.
Closing the reusable Work editor with Discard also resets its hidden draft and
dirty flag, so it cannot continue blocking the main-window switches.
The main selection, focus, expansion, view/filter/sort and scroll are preserved.
Write failure leaves the prior display, requires reload and never retries;
post-commit read/Inventory refresh failure is reported as saved with stale display,
not as an unsaved edit. A visible warning explains that waiting jobs retain their
old configuration fingerprint and may stop after any Watchlist edit. No CLI,
schema, browser or site behavior changes are introduced.

Verification uses isolated synthetic Catalog/Watchlist/management fixtures, Qt
mouse/keyboard events, CAS/write/read-failure injection and existing GUI/execution
regressions. The final affected group passed 299 tests, zero skipped
(`.tmp/discovery-toggle-affected-final.xml`); the final Work-editor/discovery
group passed 44 tests, zero skipped after the Discard fix
(`.tmp/discovery-toggle-editor-final.xml`). Whole-tree ruff and diff checks pass.
`tools/gui_discovery_switch_screenshots.py` renders only synthetic inputs; native
Windows captures at 1400x850 and 980x700, DPR 1.5, plus saving and saved/refresh-
failure states are in `.tmp/discovery-native-final-screens/` with actual metadata.
The initial full-suite attempt displayed an artificial-browser failure and
stopped progressing while ComicFUZ tests were running; it was interrupted rather
than counted as a pass. Its failing node/cause was not captured and is unresolved.
The unchanged ComicFUZ adapter browser file then passed all 69 tests, zero skipped
in isolation (`.tmp/discovery-comicfuz-check.xml`), so the initial issue did not
reproduce there. The remaining suite completed with 6,040 passed and four failures,
zero skipped (`.tmp/discovery-toggle-broad.xml`, 3,223 seconds). These four
Hanayume Discovery browser cases hit Windows directory
path limits (WinError 206) under the long test base directory. The same four
cases passed unchanged using the shorter `.tmp/h` base (4 passed, zero skipped;
`.tmp/discovery-hanayume-short.xml`). No application, site or machine setting was
changed to work around this test-output-path issue.
Together these partitioned runs cover all 6,113 collected cases (Unit,
browser-backed Integration and Research regression tests), zero skipped; every
failed case has a passing short-path rerun. This is not a successful single
uninterrupted full-suite run, and the initial interruption remains unexplained.
No live-site or account operation is needed for this UI.

`screenshot-crawler-gui` / `python -m screenshot_crawler.gui` is an optional
PySide6 inventory, selected-execution, and job-management UI. Install `.[gui]`;
the regular CLI has no Qt dependency.
See [GUI usage](../docs/GUI_README.md) and
[current contract](../docs/GUI_INVENTORY.md). P2 adds an explicit selected-key
execution boundary. `BatchPlanner.plan(selected_keys=...)` filters the candidate
Source pool before Policy allocation while calculating shared site Quota from all
site Sources. `None` keeps legacy whole-site CLI behavior; an explicit empty
selection produces no candidates. Normal Discover / Batch / Grant-only now create
a lightweight configuration-bound request without a detailed preview dialog.
Request creation does not rebuild Inventory, run BatchPlanner, or hash the Catalog.
The request is queued in a separate management SQLite DB and launches a Qt-free
worker subprocess outside the GUI event loop. The worker appends structured
JSONL events, runs selected sites sequentially under the existing Catalog lock,
and the GUI imports events idempotently. Before browser access the new worker path
validates Watchlist/runtime/environment revisions, effective endpoints, execution
options and every selected key/site/Resource, without Inventory or a duplicate
candidate plan. The common CLI plans against the latest Catalog under the lock;
earlier jobs' Catalog updates alone do not invalidate a request. Scope, access,
quota, numbering, output-collision and cancellation guards remain authoritative.
Configuration drift stops execution without automatic retry. Legacy persisted
plan-bound jobs retain their original preflight. Watchlist-save Full retains one
compact target/warning Yes/No confirmation, with no candidate count/hash display.
Metrics writer paths are emitted as
structured events and stored on the site task; a zero-candidate task carries a
`no_candidates` reason rather than implying acquisition success. Grant-only is
shown as potentially entitlement-consuming beside the execution controls. The GUI exposes one Resource selector
per selected site and serializes the exact mapping in the request; there is no
global selector that can override a heterogeneous site selection. If a reload no
longer supports the previously chosen Resource, the old value remains visible as
unsupported and submission is blocked until the operator explicitly chooses a
supported value. Queued jobs never auto-resume after
GUI restart; a cooperative stop is distinct from force termination, and an
interrupted worker leaves resource consumption unknown without automatic retry.
The history detail shows request mode/max-count, per-site Resource, and event
site/key/item/source fields with Resource consumption as yes/no/unknown.
Re-run creates a new job with the current selection and configuration.

The fixed header now has a red `緊急停止` button outside the scrollable Inventory
and monitor. Active jobs enable it; idle/queued-only states leave it disabled.
One click calls the existing `JobController.force_stop()` without a confirmation.
Before stopping, the GUI clears session queue dispatch and deferred rerun/editor
Full launch intents, so a stop failure or completion race cannot start the next
queued job. Persisted queue entries remain for explicit start. The controller
retains identity/token/OS-start checks, bounded termination, interrupted status,
unknown resource consumption and the orphaned-child new-job guard. The GUI never
assigns controller state or kills Chrome, deletes partial output or retries the
job. Stop errors remain visible and allow retry while active. Monitor and editor
state refresh after the call even though passive views do not own termination.
The Jobs-page confirmation-based emergency operation remains available.

Emergency-button verification: **121 passed, 0 skipped** across GUI execution,
main-window smoke, management jobs and both Watchlist editors
(`.tmp/gui-emergency-affected.xml`). Independent review passed and reran the five
emergency cases (idle, stopped, failure, orphaned child, broken monitor).
Whole-tree ruff and diff whitespace checks passed. An isolated offscreen sample
render checks header placement; no operational job or shared browser was stopped.
Full suite, browser-backed site Integration, Research and live verification were
not rerun for this UI-only reuse of the unchanged controller termination path.

The new request persists `fingerprint_kind="inputs-v1"` in the existing job JSON
and an `inputs-v1:` fingerprint; absent kinds retain legacy compatibility.
Optional path defaults are resolved identically for signing and execution only
on the new path. Legacy payloads retain their original empty/omitted values for
old plan validation. New-path input checks run before and after reading targets
to reject configuration changes during validation. All-disabled Discover stops;
mixed selections skip disabled targets. Batch keeps Discovery enable state
independent of acquisition eligibility.

2026-10-29 verification uses isolated Catalog/Watchlist/output fixtures, Qt
offscreen tests and fake site calls. Independent review passed; its focused
new-input/GUI tests passed 14 cases plus one smoke case. Coverage includes
multi-site direct queueing, no Inventory/preview plan, configuration drift,
key/site ownership, resource rejection, optional paths, persisted kinds, legacy
compatibility and Full Yes/No. The final affected set passed **155 tests, 0
skipped** with 55 warnings (`.tmp/gui-startup-affected-final.xml`); whole-tree
`ruff check src tests` and `git diff --check` passed. A broad full-suite attempt
was interrupted in unchanged artificial-browser tests after the last displayed 4% progress; it did
not produce a final report and is not counted as passing. The 2026-10-31
partitioned regression coverage above supersedes that older coverage limitation;
the earlier interruption remains unexplained. No live/Research test or normal
Catalog/ZIP operation was performed because adapter/browser execution behavior
is unchanged. GUI startup improvement is structural; no production timing
benchmark has been claimed.

`management.catalog_reader.CatalogInventoryReader` validates existing v7 and
reads a single `mode=ro`, query-only transaction. It creates no Catalog service,
DB, schema, migration or operational output. `InventoryService` uses frozen DTOs,
one JST evaluation time, existing Policy classes and the current flag-based
provisional numbering plan. Missing inputs fail explicitly; a failed reload visibly
marks the retained display stale. No network/CDP/browser or execution dispatch.
WAL headers are rejected before SQLite opens because read-only SQLite can update
`-shm` read marks; byte/hash verification found a mutation despite unchanged
mtime. Use an externally prepared consistent rollback-journal backup. GUI does
not checkpoint, switch journals or use immutable=1 to ignore WAL contents.

The two projections are site/work/key and work/site/key. Checked Watchlist keys
are independent of detail focus and survive filtering/view switching. Parent
selection includes hidden descendants. The right pane reads source scope, access,
recent Item Run and Artifact records. No ZIP existence checks or renumber preview.

Counts deduplicate Item IDs, preserve completed/external/skipped separately and
exclude acquisition_enabled=0 from assigned totals. Out-of-scope is a Source
count. Multiple-source conflicting access is unknown. Missing/unproved empty
inventory is —; stale observations are provisional, never certified success.
Quota pool and site-wide local slots are separate. Grant retry estimates require
Policy API and Catalog state, using runtime cooldown configuration.

Latest Run per Item and latest Artifact per Item/kind/format/backend are loaded
in the same transaction, not full historical rows. Artifact paths are DB facts,
not physical verification. Detail and tree models do not write inputs. Read-only
synthetic, Qt integration and Windows rendering verification are recorded in the
[P2/P3 progress](../runbooks/gui-execution-p2-p3/PROGRESS.md). The P3 worker stores
jobs outside Catalog in versioned `management.sqlite`, appends structured JSONL
events, records exact metrics/log paths, and uses PID/token/OS-start-identity plus
heartbeat checks. SQLite/event/log failures are fail-closed; a filesystem cancel
sentinel remains usable when management SQLite is unavailable. Partial event tails,
forced termination, and uncertain resource consumption become `interrupted`/unknown
and are never auto-retried. The Jobs page uses explicit Resume and fresh-request
rerun after restart. Native synthetic Windows captures are in
`docs/gui-screenshots/`; generation uses `tools/gui_execution_screenshots.py` and
does not start a worker or connect to a site. No real-site or paid-resource
verification is applicable.

## Catalog v7 work-key scope foundation (2026-10-22)

Catalog schema v7 adds `sources.acquisition_enabled` (`NOT NULL`, default `1`),
`acquisition_scope_sync`, and complete-listing inventory evidence tables.
Explicit v6-to-v7 migration preserves existing Source IDs, positions, statuses,
run/artifact rows and locator values. It leaves every Source enabled for legacy
compatibility but writes no successful sync marker or listing proof. Migration
alone therefore does not establish a Watchlist scope.

Watchlist targets accept optional positive-integer `archive_order`. Within a
`work_key`, every target must set it or none may set it, and values must be
unique. `enabled` continues to control Discovery execution only. The `watch add`
CLI accepts `--archive-order`; editing a group still requires an atomic complete
set of orders. Commentless Watchlist changes are serialized and revalidated
before atomic replacement. A comment-bearing file allows safe scalar
`enabled` updates with comments retained; add/remove/order rewrites fail before
writing so users can edit the YAML directly without losing comments.

`SourceInput` deliberately has no acquisition flag. New Sources use the schema
default; record refresh itself preserves existing flags, then successful
Discovery finalization reflects acquisition scope for that key. Catalog services
now expose atomic work-wide flag/sync-marker writes and complete-listing evidence
read/write APIs. Evidence binds work/key/site, target URL, adapter-provided
listing identity, ordered identities/positions and a deterministic digest. A
full inventory replacement and position-only updates affect listing evidence,
not the saved scope marker. Key/ownership changes can invalidate scope bindings;
metadata-only access refreshes preserve them. The evidence write updates only
existing Sources already owned by that key and changes no availability, access,
Item status, run, Artifact or acquisition flag.
Out-of-scope inventory entries may reference Sources belonging to another key
of the same Work; those entries are proof only and leave the other key's
Source rows, including stored positions, untouched. Cross-Work identities and
in-scope identities owned by another key remain rejected transactionally.
This supports split older/latest Discovery targets without moving ownership.
Regression coverage uses synthetic Catalog/Discovery data; the reported Jump+
split-target failure was traced against the operational Catalog read-only,
but the corrected Full traversal has not been live-verified.
Validation: Catalog, Discovery, Scope Reconciler, site scope-sync, Batch
acquisition-scope and Jump+ Discovery unit files passed (182 tests, 0 skipped);
`ruff check src tests` passed. Browser Integration, Research/Probe and the full
suite were not run for this isolated ownership-validation fix.

The P2 Scope Reconciler is implemented as a service and explicit CLI
`watch scope-sync` dry-run/apply operation. Preview is read-only. Apply reloads
the Watchlist and revalidates the Catalog snapshot under a stable per-Catalog
job lock before atomically updating every work Source flag and its sync marker.
Discovery writes complete listing evidence only after successful Full
finalization and automatically updates the successful key's classified flags.
The optional explicit reconciler requires current proof for every required
scoped/archive-ordered key. A first
unbounded/unordered legacy sync may bootstrap only when all existing Sources
have matching Watchlist key/site/work ownership. Removed Sources remain in the
Catalog disabled, with the last key/URL binding retained for safe re-add.
Batch uses current Catalog flags without requiring the scope-sync marker.
Current complete-listing inventory hooks and site-native bounded Discovery
are available for Zeblack, BookWalker, Magapoke, Jump+, Manga ONE, Piccoma,
Comic DAYS, Hanayume, Younganimal, Kadocomi, and ComicFUZ.
Comic DAYS binds its validated Atom/readable-product series inventory as
`comicdays-series:<id>`. Kadocomi opts into its native work-history inventory
only for `discovery_scope` or `archive_order`; its unconfigured legacy path
remains current-public-only and does not infer positions. Kadocomi's observed
native list is not a claim that every episode ever published is represented;
gapped episode numbers do not identify missing Sources and are never
fabricated. An existing Source missing from a complete proof blocks sync.
Cross-site `archive_order` numbering and existing-archive renumbering are
implemented through P4. P5 validates the flows on synthetic fixtures and
isolated working copies; operational Catalog/Books rollout remains a separate
operator action.

For a fully ordered work, the shared archive plan sorts Watchlist keys by
`archive_order`, then all `acquisition_enabled=1` Sources by `display_position`.
Assigned Sources reserve ordinals regardless of access mode, availability or
Item status; excluded Sources do not. No-order works retain legacy site-local
naming. GUI, Batch, audit and renumber permit provisional ordinals for incomplete
Catalog positions; only explicit scope reconciliation requires its listing proof.
Batch does not traverse historical ZIP/status files. The read-only
`scripts/check_archives.py` command reports historical cross-site naming/status drift.
The current candidate ZIP path must be absent. A sidecar may remain only when its
completed state, exact planned `archive_path`, valid page count, and same-Source Catalog
history are proven: either a matching structured output-directory identity plus at least
one successful same-Item/Source/site/external-id run at its encoded timestamp with a ZIP
Artifact, or, for tokenless legacy sidecars, unambiguous same-Item/Source filesystem
Artifact references to that path backed by successful runs. Other locator aliases and
additional same-Source runs do not invalidate structured proof; non-filesystem references
are not used as local ownership proof in the tokenless fallback, but do not invalidate
otherwise complete filesystem evidence. Foreign/malformed tokens, missing
run ownership, unreadable or ambiguous state fail closed. A proven stale sidecar is
refreshed as part of successful packaging; crawl or pre-package failure keeps its prior
bytes. If packaging has generated the new ZIP/status pair but hashing or Catalog
finalization then fails, keep the new pair for inspection rather than restoring the old
sidecar. Grant-only and resolver passes do not produce archives and skip output
occupancy checks; a later capture replan checks them. Stale candidate naming/identity,
an occupied candidate ZIP, and access-policy failures remain hard stops before site access.
`scripts/renumber_archives.py --watchlist watchlist.yaml --catalog catalog.sqlite
--work-key KEY --dry-run --json` previews all sites; managed work requires a
whole-work `--apply --json`. ZIP hashes/sizes, sidecars and Catalog locators
are preflighted, and failed apply verifies rollback or reports recovery state.

## Automatic Discovery scope reflection (2026-10-23)

Successful Discovery applies flags through
`CatalogService.apply_discovery_acquisition_flags`: one transaction, restricted
to the exact Work/site/Discovery key. Full unbounded runs enable all owned
Sources; bounded Full runs apply inventory `in_scope` flags, retaining
unclassified rows. Incremental runs enable observed Sources and retain
unobserved flags. An incomplete/failed run does not reflect new classifications;
existing flags remain, while already materialized new Sources retain their
enabled schema default. Other keys are never updated from an out-of-scope
inventory reference. This step does not scan artifacts or historical files and
does not claim a work-wide successful sync marker. Proof invalidation still
protects explicit scope maintenance; current flags remain the normal acquisition authority.
If the flag transaction fails, any Full proof just captured by that run is
invalidated before propagating the failure; strict maintenance cannot use it
as evidence of a successful Discovery.

Planner/Executor no longer instantiate ScopeReconciler or read scope evidence,
fingerprints or sync markers. They use current Catalog flags. Scope/URL edits
and another key's failed Full do not block retrieval; the next successful
Discovery reflects known rows. Removing a key alone can leave extra enabled
history; optional `watch scope-sync --dry-run/--apply` can reconcile the whole
Work without Discovery. Works absent from Watchlist remain unmanaged/skipped.
An explicit Watchlist, matching actual Work/site identity for bound keys,
pending/available state, access policy, resource rules, and output ownership
checks are still required. Capture, grant-only, resolver and replan share this
behavior. Candidate identity/current computed prefix changes require replanning.

`build_work_archive_position_plan(..., provisional=True)` is Batch-only.
Current keys follow `archive_order`; known display positions sort first,
duplicates tie-break by Source ID, then missing positions use Source ID.
Enabled removed/unbound keys follow current keys in key/position/ID order.
Unknown Sources are never invented. These ordinals are temporary and never
persisted as display positions or applied to old ZIPs. Strict scope preview,
archive audit and renumber keep their previous evidence requirements, so final
repair may use scope-sync before `scripts/renumber_archives.py`.

Changed production files: `catalog/service.py`, `discovery/service.py`,
`archive_order.py`, `batch/planner.py`, `batch/executor.py`. Regression coverage
extends Discovery, Batch acquisition scope, planner and executor tests. No
operational Catalog, Watchlist, runtime settings or Books files are changed by
this implementation. Site adapters/browser/capture logic are unchanged; this
is verified with synthetic local data, not a live site run.

Validation:

- Final broad Unit/Research run (`--ignore=tests/integration`): **3,362 passed,
  1 deselected, 0 skipped** in 189.45s. The sole deselection is the distributed
  runtime-settings test: the user's existing `crawler.yaml` sets BookWalker
  delay to 0, while the tracked configuration test expects 200. The unchanged
  test passes using an isolated copy of HEAD's distributed configuration;
  the user's settings were preserved.
- Final Discovery/scope regression run: **68 passed, 0 skipped**, including
  failure of the new flag transaction after Full proof persistence. The
  additional parameter case for this cleanup was added after broad collection.
  Comic DAYS Discovery plus the isolated config check: **56 passed**.
- Selected local browser Integration: **7 passed, 0 skipped** across the
  BookWalker Discovery-to-Batch case, five ComicFUZ Batch cases, and the
  ComicFUZ spread-to-END runner case. The old mandatory-sync expectations
  were updated; rediscovery now permits immediate replanning.
- `ruff check --no-cache src tests` and `git diff --check` pass.
- A full pytest invocation was started, then interrupted after progress had
  reported 576 cases because it had already imported the old mandatory-sync
  expectations. It reported five such failures and one additional ComicFUZ
  runner failure. Updated expectations and that runner pass individually;
  the latter failure's original cause is undetermined. **No completed/full
  suite pass is claimed.** Remaining browser Integration was not rerun after
  stopping that invocation. Live verification was not performed: no adapter,
  browser/session, site entry or capture contract changed.

Validation artifacts are under ignored `output/scope-auto-*.log` and the
isolated config fixture `output/qscfg1/`. Updated tests are
`test_discovery.py`, `test_comicdays_discovery.py`, `test_batch.py`,
`test_batch_acquisition_scope.py`, `test_batch_executor.py`, and the BookWalker
Discovery / ComicFUZ adapter browser files. Authorities updated:
`docs/ARCHITECTURE.md`, `docs/DISCOVERY_AND_BATCH.md`, `docs/DECISIONS.md`.
The current plan note (`07_catalog_position_archive_plan.md`) and all affected
site notes (`01`–`04`, `06`, `08`–`13`) now describe automatic reflection and
optional strict maintenance rather than mandatory pre-Batch scope-sync.

## Explicit historical archive audit (2026-10-23)

Historical ZIP/name/status inspection lives in
`maintenance/archive_audit.py`, exposed by `scripts/check_archives.py`.
Planner and Executor do not invoke it, including no-candidate planning,
grant-only, resolver and capture replans. Current numbering/scope validation
and exact candidate ZIP/status collision protection remain in Batch, including
same-Source stale-sidecar proof and the final pre-package recheck.

Select exactly one of `--work-key KEY`, `--site SITE`, or `--all`; `--catalog`
and `--watchlist` default to the operational filenames and must exist.
`--site` selects complete Works across all their sites. Managed Works require
current synchronized scope; legacy unordered/unmanaged Works can use their
stored site-local positions. Disabled Sources are skipped as before. The
audit only reads Catalog history and existing file metadata/status JSON; it
does not hash ZIPs, repair files, apply scope, or update Catalog. `--json`
returns one report with Work keys, findings, errors and counts. Exit codes:
0 clean, 1 findings/inspection errors, 2 invalid selectors. Example:
`python scripts/check_archives.py --site jumpplus --json`.
Renaming remains the separate strict `scripts/renumber_archives.py` operation.

An isolated comparison against the pre-change Planner (`64d8f57`) used 12 synthetic
historical ZIP/status pairs and one pending Source. Per plan, history reads
fell from 1 to 0, ZIP stat calls from 12 to 0, and historical status stat/JSON
reads from 12 each to 0; both plans retained one candidate. Three-run medians
were 17.129 ms before and 11.453 ms after, which are small-sample observations,
not real-library speed guarantees. The standalone CLI reported all 12 naming
findings and a byte snapshot confirmed that every fixture file was unchanged.
No operational Catalog, ZIP or real-site browser was used for this verification.

Validation: the affected audit/Batch/Executor/CLI/renumber/acquisition-scope
tests passed (300 tests, 0 skipped). Independent review passed with no blockers.
`ruff check src tests scripts/check_archives.py` and `git diff --check` passed.
The full suite, including Integration and Research, completed with 5,045 passed,
9 failed, 0 skipped in 2,916.91 seconds. Five Hanayume/packaging cases passed
with shorter test output paths after the long `--basetemp` caused Windows path
length failures (some surfaced as secondary assertions). Comic DAYS, ComicFUZ
and the second-process Catalog lock test passed individually after full-run
timeouts; their full-run timing cause remains undetermined. The remaining
distributed-config assertion expects BookWalker delay 200 while the user's
existing `crawler.yaml` sets 0; the unchanged test passed against an isolated
copy of the Git-managed config. The full invocation is therefore not reported
as green. No user config or site capture code was changed to clear these failures.
Live verification was not run because this change only separates offline
history inspection from Batch; no real-site entry/capture contract changed.

Changed files: `batch/planner.py`, `batch/executor.py`, `batch/archive_guard.py`,
`maintenance/archive_audit.py`, `maintenance/__init__.py`,
`scripts/check_archives.py`; tests `test_archive_audit.py`, `test_batch.py`,
`test_batch_executor.py`; specifications `DISCOVERY_AND_BATCH.md`,
`BOOK_NAMING_RULES.md`, `DECISIONS.md`; current notes `00_core.md` and
`07_catalog_position_archive_plan.md`.

# 00. Core 現行実装ノート

## Resource pass stop after successful consumption (2026-10-19)

`AccessConsumption.stop_resource_pass` is an optional, default-false site-owned
signal. Executor forwards it to normal/grant-only success results only for
matching confirmed consumption with an aware timestamp and observed-commit
semantics. CLI finishes the successful result and closes the owned Page, then
ends the resource pass without another Page or inter-candidate delay. Current
packaging, Item completion and grant persistence run before this stop. Errors
retain their existing failure paths. Pre-consumption exhaustion/unknown uses
the existing `AccessResourceUnavailableError.stop_resource_pass` mechanism.
No balance is stored in Catalog; Core/CLI interpret no site/resource names.
Magapoke uses this for a confirmed last Premium Ticket. Other adapters keep
the default behavior. Normal, grant-only and 9,000-candidate stop cases are
covered by local tests; the ticket-consuming last-ticket path is not live-run.

## Optional native expiry on observed resource consumption (2026-10-17)

`AccessConsumption` retains its existing `consumed`, `resource`, and aware
`consumed_at` fields and adds optional generic `access_granted_until`. The
Executor accepts only an aware datetime when supplied. It persists the earlier
of that native expiry and the Site Policy fallback; if native metadata is
malformed, it persists the confirmed debit with the valid policy fallback (when
available) and then raises a clear metadata error. Legacy adapters that provide
only the original fields keep their policy-derived behavior. This affects no
Runner ordering, Catalog schema, or site/resource selection. Hanayume supplies
the field from its exact target native remaining-time evidence; see
`note/10_hanayume.md`.

The Younganimal CLI registry assertion was stale: current Discovery/Batch
authority requires direct canonical episode entry, and the adapter already
resolved the configured-work case to that episode. The test now expects the
episode URL while retaining malformed-URL and missing-work-configuration
guards. This is a test correction only; no Younganimal production behavior
changed.

## Deferred grant sequencing and results (updated 2026-10-17)

`batch run --grant-only RESOURCE` / `--grant-only all` and the grant phase of
normal Batch on a Policy that defers quota entry group the planned pool by
stable Catalog Work ID. For each Work,
the CLI resolves the live target and immediately executes that single selected
grant through the existing Executor/entry-only Runner before contacting another
Work, using the same Page and Adapter without closing/reopening or reloading the
list. It preserves Planner Work order and site-owned target selection. Missing
Work identity, foreign selected IDs and multiple selected targets for one Work
fail closed. Normal Batch keeps its initial direct phase, per-Work grant phase
and one post-grant direct replan; non-deferred site passes keep their sequencing.
The normal grant phase uses the same prepared helper, with no all-Work sweep or
selected-entry reload. Only positive current-run consumption confirmations feed
Phase C; historical quota timestamps do not qualify. Remaining final capture
slots limit selected attempts and prevent later Work snapshots after the limit.
Prior direct access delays the first resolver; grant-phase site access delays
post-grant capture. Expected unavailable entry ends one Work, while fatal errors
stop before later Works and the replan. Normal output now prints the same
Work results with the heading `Grant results:`; explicit grant-only retains
`Grant-only results:`. Rows are prepared before Phase A, so a direct-phase limit
or error reports the unvisited grants as unattempted. The report counts grants
independently of capture/package completion: confirmed grants stay OK after a
post-grant capture failure. Existing metrics now include normal `grant_result`
records as well as entry attempts and observed consumption.

For grant-only CLI results, only `resource_consumed is True` confirms a grant.
`False` or `None` emits `grant_unknown`, raises the Batch error, emits no
`grant_confirmed`, and stops before the next candidate. The dedicated CLI
regression test covers both values with fake Session/Executor dependencies.
Validation on 2026-10-24: these two cases and the adjacent resource-pass case
passed (3 passed, 0 skipped, 103 unrelated cases deselected); Ruff passed.
This test-only addition preserves production behavior. Integration, Research,
live verification and the full suite were not rerun for this isolated coverage
commit; no browser or real resource is used.

The reporting follow-up on 2026-10-17 reuses `GrantOnlyReport` with a configurable
heading; it does not change resolver/entry/capture order or consume additional
resources. Normal reports cover only planned deferred Works, not all Watchlist
entries or direct-only captures. Latest matching Watchlist labels and Catalog
fallbacks are identical to explicit grant-only. Grant budgets use remaining
Phase A slots when assigning `limit_reached` to unvisited rows. Validation:
CLI/deferred reporting tests 134 passed, 1 known Younganimal registry failure
(already reproduced with unchanged HEAD), 0 skipped; browser entry Integration
48 passed, 0 skipped. A targeted 2-case capture-failure rerun also passed after
strengthening the final-list assertion (46 unrelated cases deselected, not
skipped). Tests cover unvisited rows after direct-phase failure/limit, per-Work
outcomes/metrics, fatal entry and confirmed grants remaining OK after later
capture/finalization failure. Ruff and whitespace checks passed. Full suite,
Research and live verification were not run for this reporting-only follow-up;
no real ticket was consumed.

2026-10-17 validation: affected CLI/deferred-grant/Batch/Executor/Zeblack
policy/resolver tests: 246 passed, 1 existing Younganimal registry failure,
0 skipped. The failure (series entry expected, episode entry returned) also
reproduces with the unchanged HEAD CLI loaded in an isolated process. Synthetic
Zeblack browser entry Integration: 46 passed, 0 skipped, including normal Batch
with both observed modal variants, one list load/click, grant persistence,
post-grant direct dispatch, and consumption evidence after finalization failure.
Multi-Work local tests cover order, remaining-slot limits, no later snapshots,
cooldown/unavailable/missing-target handling, fatal interruption/access stops,
and rejection of historical quota timestamps as current-run grant evidence.
`ruff check src tests` and `git diff --check` passed. Full suite and Research
were not run: this changes deferred CLI orchestration (currently Zeblack), with
no Core/Runner/browser/schema/parser change. No real-site grant or capture was
performed; the normal Batch sequencing change still needs live verification.
CLI options, output locations and the shared CDP/profile contract are unchanged.

The inter-candidate delay separates consecutive site-accessing Works after
cleanup, even when the resolver selects nothing. There is no artificial delay
inside the same-page snapshot/entry operation. Catalog-only skips
neither open Pages nor introduce extra waits. Grant-only limit counts selected
entry attempts (including unavailable attempts); a reached limit prevents later
Work snapshots. `all` retains its Policy order and shared attempt budget.

`batch/grants.py` owns display-only Work results. `batch run --watchlist PATH`
defaults to `watchlist.yaml`; Source.discovery_key + site + Work.work_key match
the latest label. Missing/mismatched labels fall back to Work.title with
`[Catalog名]`. Packaging metadata, URLs, enable state and execution scope do not
depend on those labels. Each planned deferred Work/resource has one OK/NG result,
local SKIP with a next check time, or `未実行` (stopped/limit_reached).
Unselected siblings do not become extra NGs.
Resolver-only unavailable/missing targets are visible. Expected unavailable entry
ends the current Work; ambiguous state, timeout, cancellation and access rejection
still stop the run. Only planned deferred Works are included, not every Watchlist
entry or completed/active-grant Work with no deferred candidate.

Deferred grant results print immediately and as a final list on success, failure or interruption,
and flush `grant_result` JSONL records without changing candidate counters. Both
normal Batch and grant-only Executor paths propagate validated positive
current-attempt consumption in `BatchExecutionError.resource_consumed`; a later
failure keeps that evidence independently of packaging or interruption. For a
consuming candidate, CLI failure output distinguishes confirmed resource use
with failed follow-up work from unconfirmed use and warns against automatic
retry. Old Catalog
timestamps are never used as current-attempt consumption evidence. Shared
AccessGuard and grant-only no-capture/no-package/no-completion semantics remain
intact. No schema or site-specific Core branch was added.

`BatchExecutor.prepare_access_resource_candidates()` is an async context manager
owning the resolver Page's active Guard. It yields a single-use, context-scoped
prepared handle. `execute_grant_only_candidate(prepared_access=...)` validates
the selected candidate against that handle and supplies the same adapter/guard
to Runner. Runner's internal `prepared_entry` requires `entry_only`, a borrowed
guard and positive `adopt_prepared_access_entry()` validation; otherwise it stops
without navigation fallback. Default entry still creates and closes its own
guard and navigates normally. The prepared owner keeps one guard active through
snapshot, entry and consumption confirmation, then actually awaits bounded guard
cleanup (rather than cancelling close before it can run). It prevents duplicated
response metrics and rejects handles used after context exit.

Zeblack's policy now uses the existing work resource-state table for confirmed
consumption and a default 23-hour local negative gate; a site setting can override
`work_ticket_cooldown_hours`. Explicit grant-only gates before Page creation,
normal Batch filters cooling Works before each Work resolver, and other direct reads
remain eligible. `grant_only_retry_at()` optionally exposes a policy-owned next
check time. Normal consuming-resource and grant-only local cooldown SKIPs use
the same CLI formatter: when this hook returns a time, stdout and any
grant-only report show the next check time; when the hook is absent or returns
`None`, they retain the reason-only output. Metrics continue to record the skip
reason without a retry timestamp. Expiry permits live checking but proves no
ticket.
Only confirmed consumption creates state, including after later finalization
failure. Old rental deadlines and manual usage do not backfill work state.

Validation uses local CLI/Catalog/Executor/policy tests and synthetic browser
entry, Core local-viewer and AccessGuard tests. The browser test uses the real
CLI/Executor/Runner and Blob viewer, counts one list load and one ticket click,
and proves the next run creates no site Page during cooldown. Changed/reloaded
document, wrong Page/target, reused handle, unsupported adoption, paid control
and a stopped guard fail before consumption. The source/work timestamp persists
even after a simulated post-consumption finalization error. No real Work Ticket
was spent; this new handoff is not yet live-verified. Known unrelated baseline:
Younganimal registry test expects a series entry where its adapter now returns
an episode; this was reproduced with the pre-change CLI. Research is unchanged.

Final verification (2026-10-14): all 2891 collected tests were covered by the
complete tests/unit tree (1779 passed, one known registry failure), tests/research
(117 passed), and four disjoint Integration partitions (990 passed, four initial
failures; no omitted or duplicated cases). The two Younganimal native-capture
cases and Hanayume's 0.4-second timing assertion passed on isolated rerun with
current code; the Younganimal pair also passed with HEAD Runner. The remaining
Integration failure is Kadocomi's foreign redirect, blocked with
`net::ERR_NETWORK_ACCESS_DENIED` on both current and HEAD Runner. Thus three of
the initial five failures passed on rerun, leaving the known registry mismatch
and environment restriction. Skipped tests: zero. After the final cleanup change,
all Unit tests were rerun and the affected real-browser entry/AccessGuard/local
viewer selection passed 41 tests. Cleanup cancellation is propagated on success
and never replaces an already active entry error. Ruff and whitespace checks
passed. Exact results, JUnit artifacts and changed files are listed in
`output/zeblack_grant_checks/summary.json`. Real-site verification is not run;
no real ticket was consumed.

## Kadocomi / ComicFUZ branch integration (2026-10-13)

The integration branch combines the current main-branch Kadocomi direct-entry
and PR-layout fixes with the existing ComicFUZ adapter and CLI registrations.
Both sites use their existing site-local contracts; no new shared Runner,
Catalog, pacing or access-resource behavior is introduced. The existing CLI
registry test also checks that both manual and Batch Kadocomi adapters resolve
Episode 7.2 directly to its canonical episode URL, alongside the ComicFUZ
registration checks. This detects the older listing-preflight entry contract
that remained on the divergent ComicFUZ feature branch. The exact Episode 7.2
normal Batch retry passed using an isolated Catalog/output; see
`note/12_kadocomi.md` for the reproduced failure and artifact audit.

## ComicFUZ Discovery, Crawl and Batch registries

The CLI Discovery registry includes `ComicFuzDiscoveryAdapter`; manual Crawl
and Batch registries include `ComicFuzAdapter`, and the Batch policy registry
includes `ComicFuzSitePolicy`. Manual Crawl requires `COMICFUZ_WORK_URL`; Batch
reads that optional value when supplied and otherwise derives the canonical
same-work listing from the configured composite Catalog identity. In both
paths the adapter validates the same-work public listing and exact current
free row before reader entry.
The policy selects only available `free` Catalog sources with `direct` access;
resource and grant-only passes are unsupported. Discovery, capture, Batch,
Runner and packaging use their existing site-neutral services and the shared
CDP BrowserSession/Page without Core or schema changes. Current contracts and
evidence are in `note/13_comicfuz.md` and
`runbooks/comicfuz-free/PROGRESS.md`.

## Historical Kadocomi registration snapshot (2026-10-12)

This section records the initial registration contract only. Current Kadocomi
Discovery scope, native inventory, and position behavior is described in the
2026-10-22 shared Catalog section above and `note/12_kadocomi.md`. The initial
public-list-only, single-work no-deadline, and no-inferred-position statements
below are superseded for opt-in scoped or archive-ordered targets.

Kadocomi Discovery, manual Crawl, Batch adapter, and Batch Policy use the
existing DiscoveryService, Catalog, CrawlerRunner, shared CDP BrowserSession /
Playwright Page, Batch Planner/Executor, and generic packager. The CLI registers
Kadocomi in those site-local registries. No shared Core, Batch, Catalog schema,
or existing adapter behavior was changed. See note/12_kadocomi.md and
runbooks/kadocomi/PROGRESS.md for live facts, current phase gates, and limits.

Discovery snapshots only the unique public EpisodesTabContents UL after
clicking the exact declared-count expansion button. It requires two identical
scoped identity/deadline snapshots and the exact declared row count, buffers and
validates all rows before yielding newest-first, and excludes recommendations.
A failed or incomplete full list cannot mark absent Sources unavailable.
Incremental Discovery leaves unseen Sources unchanged. Stable external IDs reuse
the same Catalog Source and Item, preserving Completed state, CrawlRuns, and
Artifacts after a source disappears and later returns.

Future explicit row deadlines classify free and refresh free_until; a later
NULL clears the old value. A no-deadline row is free only for the independently
verified KC_004915_S work; no-deadline rows on other works and expired
deadlines remain unknown. Inferred display positions are disabled: existing
positions remain intact and new Sources remain NULL.

The Batch Policy admits only available `kadocomi` sources with `access_mode=free`,
a strict work-scoped external ID, and a valid future or NULL `free_until`. The
Adapter requires `direct`, rejects quota/grant-only resources, and validates a
canonical query-free Catalog episode target against its configured external ID.
The Runner opens that exact episode as its single main-document navigation.
The Adapter checks the final main-document HTTP 200 response, exact work/episode
identity, consistent same-page H1/og:title/document.title metadata, no visible
dialog, and a settled recognized reader. It does not navigate to the work list
or issue a second document navigation. The generic Planner only selects pending
Items; the Executor creates ZIP Artifacts and Completed status only after the
Runner reaches the adapter's verified END. Manual Crawl also requires explicit
`direct`.
No numeric archive prefix is inferred while display positions are NULL.

The canonical work title from detail-page og:title is exposed by Discovery but
the shared DiscoveryService initializes Work.title from the Watchlist label.
Set a dedicated Watchlist label to the actual Work name. P3 policy and local
end-to-end validation passed independent review. P4 Tester, Reviewer, and Lead
accepted isolated live CLI Batch/ZIP/Completed runs for the observed 4.1 and
first-episode 38-slot variants; independent ZIP members matched every live
source Blob and full-RGBA canvas audit. The 21-slot normal CLI control and final
post-Discovery/Catalog stability audit also passed: all 53 Sources/IDs and NULL
positions remained stable, both Artifacts remained stable, and the actual-catalog
renumber dry-run proposed no moves. Final docs synchronization review passed (Reviewer BLOCKING=0, NONBLOCKING=0); Lead accepted closeout.
The prior repository-wide pytest run had
one known baseline failure reproduced at `ceb3434` before the 38-slot extension;
full Ruff passed. The direct-entry follow-up now uses one canonical episode
navigation and same-page response, identity, title, gate, and reader checks.
Its bounded live Runner probe and local Runner/Batch fixtures passed independent
code/test review. The 2026-10-13 integration verification also completed Episode
7.2 through normal live Batch CLI with 14 native WebP pages and explicit END.
Current tests and exact evidence are in the Kadocomi progress ledger.

## Younganimal Discovery and manual Crawl CLI registration (2026-10-11)

Younganimal Discovery, manual Crawl, and direct-only Batch use the existing
DiscoveryService, Catalog, CrawlerRunner, shared CDP BrowserSession/Playwright
Page, AccessGuard, BatchExecutor, and packager. The site is registered in the
Discovery, crawl, Batch adapter, and Batch Site Policy registries. Manual Crawl
reads YOUNGANIMAL_WORK_URL from the selected env file as its canonical initial
series route while preserving the requested episode URL as the output source
URL. Batch uses the canonical Catalog episode URL as its sole initial
navigation and requires a configured strict work/episode external identity.
Only available Catalog sources with `access_mode=free` are Batch eligible. No
Core branch or Catalog schema field was added. Site-local routes, entry checks,
capture contract, and live-verification status are in note/11_younganimal.md.

## Hanayume Discovery, Viewer, and Work Ticket Batch (updated 2026-10-17)

`HanayumeDiscoveryAdapter` is registered in the Discovery registry. `HanayumeAdapter` is registered in the manual crawl and Batch adapter registries, and `HanayumeSitePolicy` is registered in the Batch policy registry. All paths use the shared CDP BrowserSession/Page and existing DiscoveryService/Planner/Executor/Runner/Packager; no Hanayume-specific Core branch or Catalog schema field was added. Discovery authentication reads the canonical series route under `series.mode-series-top[data-e2e=pageSeries]`; episode row identity uses `div.ep-main.series-safe-filter-target[data-e2e=pageEpisode] > div.series.mode-ep` (the inner `.series.mode-ep` has no `data-e2e`). Both enumerate only a unique direct public `epList`; known history siblings are checked for overlapping badge conflicts, never merged into Discovery results. Authenticated Hanayume range snapshots wait boundedly for the observed episode-local account root to settle; exact native active grants can cover public-enumerated episodes outside the short account preview, while a present account row still requires its rental marker. This remains Hanayume-local behavior.

Discovery consumes only the natural exact work/episode `/api/series/access` observation: native `accessType=waitAndFree` promotes an otherwise unknown row to a nominal `quota` candidate, while exact free labels retain their established precedence. This classification never authorizes an entry click. Full and incremental Discovery refresh the already-buffered validated ranges without extra range/API requests and wait up to five seconds for each authenticated episode-local account root to settle. A manual episode grant requires fresh authenticated series markers plus an exact native `waitAndFree` row with `hasAccess=true` and strict positive remaining seconds (1..259200). When that episode appears in the short account preview, its row must show the observed read/rental markers; a present row without them is contradictory. Absence from the preview is not negative evidence when the exact active native row is present. Unknown/loading/no-user/malformed states preserve prior grants; exact zero remaining clears a stale grant. Only this exact active grant permits a public/history label difference. Catalog stores normalized `access_mode` and source-level `access_granted_until` provenance, not raw labels or native response payloads. Batch selects from Catalog and opens only the chosen canonical episode URL; `work_ticket` uses a work-scoped minimum 23-hour cooldown and one candidate per work, while each episode grant lasts up to 72 hours. Direct access during a recorded active grant does not consume another ticket. No site-specific Core branch or Catalog schema migration was added; shared `AccessConsumption` has an optional generic native expiry. Current site behavior, tests, evidence, and limits are in `note/10_hanayume.md` and `runbooks/hanayume-work-ticket/README.md`.

The site-local manual Viewer path freshly checks the same-work row before capture and its label again after episode entry. Login/paid entry dialogs or unavailable viewer structure fail closed without CTA actions. The document-start Hanayume source observer snapshots an opaque sRGB/unorm8 full-frame canvas at its actual dimensions (up to 4096 per side and 4,000,000 pixels) and requires exact selected-canvas RGBA replay. Verified pixels use strict lossless VP8L WebP method 4 with full RGBA round-trip validation; encoder failure keeps the same verified native PNG at the same dimensions. Missing/unsafe/over-limit native proof stops capture without rendered PNG. The site-local cache is bounded to eight candidates and 12,000,000 source pixels. A separate variable-size live check verified 30 Yona pages at 960x1508 and 12 control pages at 960x1540 against independent source-canvas RGBA, all at END without new resource consumption; old archives were not changed. This does not claim original JPEG bytes or tile reconstruction. Final live E2E verified 134/134 original 960x1540 source-canvas pages as single-chunk VP8L lossless WebP with exact independent RGBA equality and zero rendered fallbacks. Four candidates reached END and produced four verified ZIPs without quota or entitlement mutation. The prior 122-page Phase 05 rendered-PNG run is historical baseline evidence. Details and limits are in `note/10_hanayume.md` and the Hanayume runbook.

## AccessGuard selector cancellation (2026-10-10)

The shared visible-CAPTCHA provider selector check now re-raises
`asyncio.CancelledError` before its best-effort Playwright-error handling. This
allows the monitor task to terminate when `AccessGuard.close()` cancels it
during a pending selector operation. A unit regression uses a blocked locator
count to reproduce and verify prompt cleanup. Access-stop classification,
relevant-host rules, and response handling are unchanged.

## Piccoma current adapter registration (2026-10-09)

The Discovery registry includes `PiccomaDiscoveryAdapter`; the manual crawl and Batch adapter registries include `PiccomaAdapter`; and the Batch Site Policy registry includes `PiccomaSitePolicy`. The adapters use the existing BrowserSession/CDP Page contract. Manual access strategies are limited to `auto` and `direct`, both requiring a fresh exact-free product-listing check. Batch policy admits only available sources classified as free and uses the normal direct path; all other access modes are rejected with no resource or grant-only passes. Viewer/Capture and local Batch integration behavior are summarized in `note/09_piccoma.md`; independent Phase 04 review passed with BLOCKING 0 (130 passed, 0 skipped), and Phase 05 live Discovery-to-ZIP E2E passed for one free episode from each product. The earlier Phase 06-B live Batch-to-ZIP and PNG comparisons are historical. Phase 06-D's default native result is lossless WebP only after strict Piccoma-local JPEG tile replay, proven white compositing, single-VP8L validation, and exact full-RGB round-trip. Verified native pixels remain PNG if encoding fails; guarded Core fallback remains PNG. Phase 06-D code review and independent live Tester passed with BLOCKING 0: all 39 pages in the two-product Batch-to-ZIP run used the validated WebP path. Focused Piccoma, packaging, Ruff, and diff checks passed; the full suite was not rerun after the final site-local adjustments. Other layouts/resources and unobserved draw/backdrop variants remain unsupported. Details and limits are in `note/09_piccoma.md` and the Piccoma runbook progress.

## Read-only episode-list helper CLI (2026-10-01)

`python -m screenshot_crawler.cli episode-list --url <URL>` is an operator
helper for selecting bounded Discovery endpoints manually. It recognizes only
the strict Zeblack chapter-list URL and Jump+ episode URL parsers, connects to
the shared CDP browser session, creates an in-memory `WatchlistTarget`, and
calls the matching existing Discovery adapter's `iter_records(page, target,
"full")`. It does not call `DiscoveryService.discover()`, `CatalogService`,
or `WatchlistService`, and it does not write `watchlist.yaml` or Catalog data.

Each retained record is printed in adapter order as tab-separated
`order_key`, visible `order_label`, and canonical `source.url`. A missing
`order_key` is shown as `-` so special episodes are retained. Repeatable
`--contains TEXT` applies an exact substring OR filter to the combined order
key/title display text; it is only a display filter and never chooses a
boundary. `--env-file`, `--cdp-endpoint`, and optional `--keep-open` follow the
existing CLI/CDP session contract. Unsupported URLs and adapter listing or
validation failures exit with a concise error, and the created page/session
are always closed while the remote Chrome remains running.

## Current shared Batch extension (2026-09-30)

Batch retains the generic planner/executor and existing non-Zeblack behavior.
Site Policies may opt into a small site-owned access-resource resolver. The
resolver runs under the shared AccessGuard, receives already-planned pending
candidates, returns selected source IDs plus expected local skip reasons, and
does not count its read-only site snapshot as a candidate attempt. This is an
optional extension point, not a site-name branch or YAML rule DSL.

Zeblack is the current consumer: its Work Ticket resolver reads one native
chapter/list snapshot per Work/title, matches live availability to Catalog
external IDs, and then reuses the existing grant-only Executor. Its normal
Batch phases are direct, grant-access, and one post-grant direct replan.
The generic deferred path derives the resolver resource from the planned
candidate `quota_resource`; missing or mixed deferred resources fail closed and
no site-specific resource name is interpreted by the CLI. The resolver is a
site access for `inter_candidate_delay_ms`: a previous site access is followed
by a delay before resolution; the selected grant immediately reuses the same
Page/document/Guard. Page cleanup and one delay separate Work operations and
the post-grant direct phase. A resolver with no selected candidate still updates
the explicit-pass pacing state, while local-only skips do not. Catalog
schema/version and the shared browser/CDP session model are unchanged.
Resolver navigation and protobuf body reads share one bounded observation
deadline, and resolver cancellation is propagated rather than swallowed.
Resolver operation and AccessGuard cleanup joins are bounded and detached
best-effort when a Playwright task does not respond to cancellation.
The generic Batch CLI reports resolver start, completion, and failure so a
deferred-resource phase remains observable while its read-only snapshot runs.
For policies that defer quota access, the CLI also partitions the unchanged
plan by `candidate.consumes_quota`: immediate candidates remain individually
visible, while deferred candidates are shown only as a pool summary with their
candidate count and policy-owned resource. The generic partition has no site
or resource-name branch, and non-deferred site output remains unchanged.

Comic DAYS is a non-deferred policy: Discovery full classifies the complete
first-party listing and is the authority for quota candidates. Its policy uses
work-scoped `work_ticket` state with `quota_limit=1`; Planner therefore passes
at most one quota candidate per work in existing Catalog order. The generic
Executor exposes an optional `SiteAdapter.configure_target_identity()` hook
before Runner navigation, allowing a site adapter to compare Catalog identity
with the target page. It also evaluates work-scoped local resource cooldown
state before opening a page for any consuming candidate. These are neutral
hooks; no site or resource name is interpreted by Core.

Comic DAYS no longer uses a production live candidate resolver. Its adapter
opens the selected target once, performs target-local identity and exact Work
Ticket safety checks, clicks once, confirms positive debit/unlock evidence,
and continues normal quota crawling on the same Page. Positive Catalog/live
identity or contract disagreement stops the resource pass and requests a new
full Discovery; a positive `isCharged=false` is reported as a distinct
`work_ticket_cooldown`. The shared resolver framework remains for Zebrack,
whose Discovery cannot classify native per-chapter ticket state.
The generic Executor validates a populated candidate external ID against the
Catalog source before opening a page. Comic DAYS treats charged-without-
`chargedAt` as unknown; the target-local safety path cannot infer a click
baseline. CLI stop-pass output is neutral, while the adapter reason remains
available for operators and metrics.

## Entry-only success diagnostics (2026-10-06)

The generic `BatchExecutor` now best-effort collects the adapter's existing
`collect_debug_metadata()` after a confirmed grant-only entry and writes
metadata-only `diagnostics/entry_trace.json` under that candidate's existing
output directory. The file carries `item_id`, `source_id`, `target_id`, `site`,
and `resource`; collection or write failure never changes the candidate result.
This is a generic hook extension and has no site-name branch. Comic DAYS puts
its bounded `ticket_trace` inside `adapter_debug`, and the existing Runner
failure diagnostics expose the same field under `metadata.json`'s
`adapter_debug`; no capture, retry, pacing, timeout, click, or Catalog
semantics are changed.

## Zeblack Z5 current status (2026-09-30)

### Z5-6 production initial-navigation and Work Ticket flow

The generic `SiteAdapter` contract now has the synchronous
`resolve_initial_navigation_url(source_url)` hook. Its default returns the
canonical `source_url`; `CrawlerRunner` calls it after run/resource validation
and uses the result only for the first browser navigation. `source_url` remains
the identity stored in ProgressStore, CrawlRun, BatchCandidate, and
SourceTarget.

Zeblack stores the canonical viewer target as `_target_url` / `_target_viewer`.
For `quota + work_ticket`, the hook strictly parses that viewer URL and enters
`/title/{title_id}/chapter/list`; malformed, foreign, or non-viewer targets fail
closed without falling back to direct viewer navigation. `direct` and `auto`
retain the viewer URL as the initial browser entry.

The quota Adapter observes live protobuf status and `target.main_name`. For
`TICKET_AVAILABLE`, it validates one visible target chapter row and one exact
mainName descendant, clicks that chapter control once, requires the exact
chapter-list URL to remain, validates the visible modal identity (mainName,
`チケットを使って読む`, `キャンセル`) in one bounded DOM scope, and rejects
point/item/coin/purchase controls. It clicks the exact ticket control at most
once, waits for the same target viewer and stable `page_N` content, and only
then records `AccessConsumption(consumed=True, resource="work_ticket")`.
FREE / RENTAL skips the modal and navigates to the target viewer for normal
runs; entry-only returns `work_ticket_not_needed` without that navigation.
POINT/unavailable statuses retain the existing resource-pass skip behavior.

The observer still owns its existing chapter-list navigation, so quota entry
currently performs an initial Runner list load plus one bounded observer reload.
This is an accepted initial implementation constraint and the observer remains
the live protobuf authority. No real Work Ticket was consumed by this change;
the controlled live click/consumption verification remains a separate follow-up.

### Current live verification: title 66 / chapter 6077

The latest `main` commit `e990c97` was reviewed. Shared-CDP read-only
observation decoded 229 title-66 protobuf records with
`FREE=3`, `RENTAL=0`, `TICKET_AVAILABLE=1`, `POINT=193`, and `COIN=32`; the
oldest/current ticket candidate was chapter `6077`. Bounded singleton
Discovery and Batch planning completed with one `work_ticket` quota candidate,
and the temporary Catalog initially had a pending Item with no quota state,
CrawlRun, or Artifact.

The final preflight immediately before grant-only still saw
`TICKET_AVAILABLE`, but the production `--grant-only work_ticket --limit 1`
run observed `RENTAL` with preexisting same-chapter content and safely skipped
as `work_ticket_not_needed`. No exact ticket click, point/coin/purchase
fallback, `AccessConsumption`, or quota timestamp occurred. A separate normal
run then verified the RENTAL path: no additional ticket click, 19 source-native
JPEG pages at `760x1200`, `next_content`, ZIP Artifact, and `Item=completed`.
Post protobuf state was `RENTAL=1`, `TICKET_AVAILABLE=0`; the transition is
not attributed to an exact ticket action by this run. Work Ticket consumption
remains unverified, so Zeblack Z5 is **BLOCKED**, not COMPLETED.

### Current live verification: title 53 / chapter 4844

The current shared-CDP verification observed 411 title-53 protobuf records.
Before the controlled attempt, counts were `FREE=3`, `TICKET_AVAILABLE=1`,
`POINT=377`, `COIN=30`, `RENTAL=0`; the oldest/current candidate was chapter
`4844` (`標的4 退学クライシス`). Title-top UI independently showed
`チケットでさっそく読もう！ × 1`, but this remains diagnostic only.

Full Discovery and a bounded singleton Discovery completed read-only. The
singleton Batch plan had one eligible quota candidate using `work_ticket`.
The Adapter was corrected so live protobuf status is consulted before locked
viewer `page_N` placeholders are considered preexisting content; viewer
hydration is also bounded before and after the same-page live preflight.

No exact Work Ticket control was clicked. The later post-observation reported
`FREE=3`, `RENTAL=1`, `TICKET_AVAILABLE=0`, `POINT=377`, `COIN=30`, with target
`4844` now `RENTAL`. This transition is not attributed to the read-only or
skipped grant-only checks. The normal RENTAL run then completed with the
site-local ad and last-page interstitial handling, `next_content` stop, 19
source-native JPEG entries, and a present ZIP Artifact. The Item is
`completed`; Work Ticket consumption remains unverified and no quota timestamp
was committed.

Zeblack now has both production Discovery and a registered Batch Site Policy.
Catalog `quota` remains a broad candidate class, while explicit quota runtime
uses a site-local live `title_chapter_list` protobuf preflight. The Viewer
Adapter only attempts a single exact ticket-only control when the target live
status is `TICKET_AVAILABLE`; POINT/COIN/unknown states fail closed or return
the generic resource-unavailable result. Confirmed same-chapter content is
required before `AccessConsumption` is recorded. `work_ticket` is the only
supported Zeblack resource, with no local cooldown/capacity inference and
`after_observed_consumption` persistence. Grant-only reuses the generic
entry-only path and leaves Items pending without packages.

The 2026-09-30 Z5-1 check did not consume a ticket. Human observation confirms
that selecting/opening a `TICKET_AVAILABLE` chapter only reveals the next
entry action; consumption starts only when the exact `チケットを使って読む`
action is clicked. The check stopped before that action, so no ticket action
was performed and no grant-only run was executed.

The later protobuf observation showing the target as `RENTAL` and removing
all `TICKET_AVAILABLE` IDs is not attributed to this read-only check. The
temporary singleton Discovery/Batch plan completed read-only and the
temporary Catalog remained pending. The point path is separate: a point
chapter exposes `ポイントを使って読む`, which is never a valid fallback and
must not be clicked. The existing direct Z3 capture path and Z4 Discovery
boundary remain intact.

## Zeblack Z4-1 status (historical baseline)

Zeblack production Discovery is implemented. The adapter is registered in the
Discovery registry, supports unbounded full/incremental and site-native
bounded Discovery. The current Z5 policy registration is described above.
Discovery validates the chapter-list DOM and the exact
`title_chapter_list` protobuf response before yielding. It uses
`chapter_id` identity, latest-first canonical order, explicit access-mode
mapping, and inclusive viewer URL boundaries. The existing Zeblack Viewer
Adapter and crawl lifecycle are unchanged. Zeblack Site Policy and access
resource consumption are not implemented in this phase.

## Phase 4A Discovery status

`MangaOneDiscoveryAdapter` is now registered for `mangaone`. It reads an
arbitrary chapter URL's `#chapterList` newest-first, follows bounded 10-item
pagination, and uses the chapter id (not the URL) as source identity.
`無料`/`FREE`, `先読`/`先読み`, and unbadged cards map to `free`, `paid`, and
`quota`. Incomplete traversal is not treated as a complete full scan. The
adapter remains Catalog-free and does not own BrowserSession lifecycle; the
minimal `discover` CLI supplies the Page. BookWalker series-scoped Discovery
is now registered. BookWalker Site Policy, grant-less quota consumption, and
automatic Batch execution are implemented, while BookWalker strict
direct/quota product-page entry remains in the BookWalker Adapter. Phase 5A adds
read-only Batch planning and Manga ONE Policy. Phase
5B adds sequential Manga ONE Batch execution around the existing Core.

このファイルはScreenshot Crawler Coreの**現在の実装詳細**と、採用済みのBrowser Session移行方針をまとめる。Core / Runner / browser / output / packaging / diagnostics / resume方針を変更した場合は、このnoteも同じ変更で更新する。

最終同期: 2026-10-02

### Test execution policy（2026-09-27）

テスト分類・選択・実行範囲のauthorityは `docs/TEST_STRATEGY.md`。

2026-09-27の実測では、full pytestは約4分で完走可能だったが、`tests/unit/` に実Chromiumを起動するtestが混在し、productionのpacing / timeoutを実時間で待つtestも存在することを確認した。詳細な測定snapshotは `note/test_suite_audit.md` に保存している。

現在の運用方針:

- 全変更で `pytest -q` を必須にしない
- 開発中は変更した契約に直接対応するtargeted testを使う
- 完了前に影響範囲のUnit / Integrationへ広げる
- shared Core、共通data model、大規模refactor、複数site変更、影響範囲不明ではfull suiteを実行する
- 実browser / DOMを使うものはIntegration相当、`poc/` を直接検証するものはResearch / Probe相当として扱う
- productionの実時間delay / timeoutそのものが検証対象でなければ、testではfake / injection /短いtest-specific timeoutを使う
- 最終報告では実行testsに加え、Integration / Research / Live / full suiteを未実行なら理由を書く

Phase 2Bでは、Research / Probe 4 filesを`tests/research/`へ移動し、mixed 8 filesを
Unit / Integrationへ分割した。Phase 2B-3完了後の実測collectionは785 cases
（Unit 610 / Integration 129 / Research 46）で、targeted / category / full pytestを
passした。`tests/unit/`には実Chromium起動testを残しておらず、browser / DOM boundaryは
`tests/integration/`、`poc/` / probe実装の検証は`tests/research/`に配置している。

`pytest -q tests/unit tests/integration`はproduction regression、`pytest -q tests/research`
はResearch / Probe regression、`pytest -q`はResearchを含むrepository-wide regression
である。Phase 2B-3のruntime baseline（`-p no:warnings`）は Unit 52.48s、Integration
169.99s、Research 0.46s、full 223.66s（通常の`pytest -q`はwarning込み250.67s）だった。
BookWalker AdapterはPhase 2A計画の18 Unit / 25 Integrationに対し、現行testを実際の
browser依存で分類すると17 Unit / 26 Integrationとなる。この1 case差分はtest semanticsを
変えずに解消できないため、classification planのOpen Questionとして残している。

今回は高速化、fixture scope変更、test semantics変更、pytest設定変更、production code
変更を行っていない。browser起動回数、実時間wait、timeout / pacingの最適化はPhase 3
以降の課題である。

### Phase 3A test runtime optimization (2026-09-28)

Phase 3A removed real production inter-candidate pacing waits from the five
resource-pass and grant-only orchestration tests in
`tests/unit/test_cli.py`. Those tests now replace the CLI module's async sleep
with a no-op async fake, while retaining their ordering, replan, limit,
resource-exhaustion, and failure assertions. The existing pacing contract
test remains responsible for checking the configured delay, seconds
conversion, between-candidate placement, and no-delay-after-the-last-candidate
behavior. The production default `inter_candidate_delay_ms = 3000` is
unchanged.

Measured runtime:

| Scope | Before | After |
| --- | ---: | ---: |
| `tests/unit/test_cli.py` (63 cases) | 25.75s | 1.11s |
| `tests/unit` (610 cases) | 52.48s | 31.10s |
| full pytest, `-p no:warnings` (785 cases) | 223.66s | 198.89s |
| full `pytest -q` (785 cases) | 250.67s | 205.04s |

The full-suite slowest tests remain Integration/browser wait tests; Phase 3A
did not change browser fixtures, Manga ONE timeouts, production runtime
behavior, pytest configuration, or test counts.

### Phase 3B test-specific Integration wait optimization (2026-09-28)

Phase 3B shortened only waits that are not themselves the contract under test.
The changed Integration tests use existing test-side configuration seams:

- Manga ONE viewer-missing failure uses `page_change_timeout_ms=200`.
- Manga ONE grace-period tests use `page_change_timeout_ms=500` and
  `end_grace_ms=200`.
- Local viewer Runner tests use `page_turn_delay_ms=0` because page-turn pacing
  is not their contract; state transitions, same-content guards, and max-page
  assertions remain unchanged.
- The Magapoke terminal-card Runner test uses
  `page_change_timeout_ms=500` and `page_turn_delay_ms=0`; its 150 ms fixture
  transition and terminal-card assertions remain unchanged.

Production timeout/grace defaults, polling algorithms, browser fixture scope,
Chromium launch count, and production code are unchanged. No pytest-only
environment branch or global test mode was added.

Direct Phase 3B measurements before the change were 129 Integration cases in
177.83s and 785 full cases in 208.56s with `-p no:warnings`. After the change,
Integration remained 129 cases and ran in 139.70s; the full warning-suppressed
run was 790 cases in 181.43s, and standard `pytest -q` was 790 passed in
168.58s with 2,774 warnings.

The full collection became 790 during this work because a separate, user-owned
five-case Research addition (`tests/research/test_jumpplus_vertical_probe.py`
and `poc/jumpplus_vertical_probe.py`) appeared in the working tree. That
addition and its `note/04_jumpplus.md` update are not part of Phase 3B and were
not modified or staged. The Phase 3B changes themselves preserve the previous
785-case taxonomy: Unit 610 / Integration 129 / Research 46.

### Phase 3C-1 Magapoke browser lifecycle proof (2026-09-28)

The Magapoke Adapter browser tests now use module-scoped Playwright and Browser
fixtures, with a fresh function-scoped BrowserContext and Page for every test.
The target file remains 43 cases. Direct measurement changed the target-file
runtime from 29.15s to 8.39s; lifecycle instrumentation showed Playwright
starts 43 -> 1, Chromium launches 43 -> 1, and Context/Page creation at 43 / 43.

The repeated target-file runs were 9.08s and 9.11s, and the full Integration
suite ran 129 passed in 121.34s. The standard full suite ran 801 passed in
152.09s with 2391 warnings. No order dependency, browser crash, cleanup leak,
or Chromium skip was observed. The target file uses an explicit module async
loop scope to keep module-owned Playwright objects on the same loop; pytest
configuration was not changed.

Only `tests/integration/test_magapoke_adapter_browser.py` and this note were
changed for Phase 3C-1. Production code, test semantics, timeout/grace values,
other Integration files, and shared `conftest.py` were not changed. The
current observed collection is Unit 610 / Integration 129 / Research 62 = 801;
the Research count was not modified by this Phase. BookWalker rollout remains
Phase 3C-2 and is pending.

### Phase 3C-2 BookWalker browser lifecycle rollout (2026-09-28)

The three BookWalker browser-backed Integration files now use the shared
`tests/integration/conftest.py` lifecycle primitives. The fixture scopes remain
module-scoped Playwright and Browser, with function-scoped fresh
BrowserContext and Page. No Context or Page is shared. BookWalker-specific
routes, HTML, Catalog setup, and capture helpers remain local to each test
file.

Before -> after measurements:

- Adapter: 26 cases, 26 -> 1 Playwright/Chromium lifecycle, 32.30s -> 18.50s.
- Discovery: 19 cases, 19 -> 1 Playwright/Chromium lifecycle, 27.11s -> 17.55s.
- Original Capture: 4 cases, 4 -> 1 Playwright/Chromium lifecycle,
  2.57s -> 0.98s; its three test-local extra Context/Page pairs were retained.
- Combined target: 49 passed; repeated runs 36.74s and 36.37s.
- Integration: 121.34s -> 90.79s in the first after run; the final
  verification run was 101.65s for 129 passed due to unrelated local-viewer /
  wait-test runtime variance.
- Full: the latest run was 816 passed in 149.14s with 2079 warnings. Latest
  collection was Unit 624 / Integration 129 / Research 63 = 816; Unit and
  Research changed because unrelated user-owned changes appeared during the
  work and were not modified.

`--setup-show` confirmed three module Playwright fixtures, three module Browser
fixtures, and 49 function Context/Page fixture invocations. Repeated and full
runs showed no order dependency, loop ownership error, browser crash, cleanup
leak, or Chromium skip. The Original Capture extra Page is explicitly closed
before its Context. Production code, pytest configuration, timeout/grace
values, assertions, parametrization, and non-BookWalker Integration semantics
were not changed in the Phase 3C-2 snapshot; Phase 3C-3 is recorded below.

The BookWalker Adapter retains its historical 800x600 viewport through a
file-local function-scoped `browser_page` fixture backed by the shared module
Browser. The generic integration fixture keeps the Playwright default viewport
for BookWalker Discovery and Original Capture.

No new test case was added for this follow-up; the existing Adapter tests and
the 49-case BookWalker group pass with the restored viewport.

### Phase 3C-3 remaining Integration browser lifecycle rollout (2026-09-29)

The final six targeted browser-backed Integration modules now use the shared
module-scoped Playwright/Browser lifecycle from
`tests/integration/conftest.py`, while keeping fresh function-scoped
BrowserContext and Page objects. The migrated files and current case counts
are:

- AccessGuard browser: 1
- generic local viewer: 19
- Magapoke Discovery browser: 6
- Magapoke local viewer: 3
- Manga ONE Adapter browser: 7
- Manga ONE Discovery browser: 1

The 37 cases therefore use six module Playwright starts, six Chromium launches,
and 37 fresh Context/Page pairs. The following three files retain their
historical 800x600 viewport in file-local fixtures:

- `test_local_viewer_flows.py`
- `test_magapoke_local_viewer.py`
- `test_mangaone_adapter_browser.py`

AccessGuard, Magapoke Discovery, and Manga ONE Discovery use the generic
Playwright-default viewport. No Context or Page is shared, and no session scope
or pytest configuration change was introduced. Phase 3C is now complete.

Measurements:

- Before: 37 passed in 39.74s, with 37 per-case Playwright/Chromium starts.
- After: 37 passed in 40.54s; repeated runs were 41.21s and 31.08s.
- Integration: 129 passed in 80.75s in the final run.
- Full: 816 passed in 115.95s, with 1770 warnings.
- Collection: Unit 624 / Integration 129 / Research 63 / Total 816.

The six-file aggregate is affected by existing test-body wait and local-viewer
transition costs, so its direct runtime did not improve monotonically. The
lifecycle proof is the reduction from 37 per-case browser owners to six module
owners while preserving fresh Context/Page isolation. Repeated target,
Integration, and full-suite runs showed no order dependency, event-loop
ownership error, browser crash, cleanup leak, or Chromium skip. Phase 3C is now
complete. The remaining Integration files were not changed, and no
session-scoped or cross-module Browser fixture was introduced.

### Phase 3D-0 runtime reassessment (2026-09-29)

Phase 3C-complete Integration runtime was remeasured without changing test or
production behavior. Three Integration runs were 81.83s, 90.72s, and 87.50s
(median 87.50s) for 129 passed; the full warning-suppressed suite was 817
passed in 120.47s. A temporary timing hook measured setup 11.298s, call
65.966s, and teardown 1.954s, confirming that test-body call time now
dominates. Phase 3D remains assessment-only; detailed slow-test and ROI
analysis is recorded in `note/test_runtime_phase3d_assessment.md`.

### Phase 3D-1 BookWalker strict-entry test-side timing (2026-09-29)

The BookWalker Adapter browser test keeps its 26 cases, shared Browser
lifecycle, production defaults, and two stable candidate samples. Six
timing-independent successful selection tests explicitly use a test-side
10ms initial settle and 20ms candidate poll interval. Persistent rejection
cases leave the timing arguments unset and therefore inherit the adapter's
production 250ms/100ms defaults because applying fast polling broadly increased
repeated DOM scans rather than reducing runtime. The helper uses `None`
defaults and writes instance attributes only for explicitly supplied overrides.
The delayed-Maruyomi and transient-duplicate timing cases retain their
300ms/350ms fixture delays and timing semantics.

The target file improved from a 17.98s median to 16.32s over three-run
measurements, a demonstrated 1.66s saving. Integration then passed 129 cases
in 87.80s, and the current full suite passed 821 cases in 115.64s. Current
collection is Unit 624 / Integration 129 / Research 68 / Total 821; the
Research increase is outside this Phase. No production code, pytest
configuration, fixture scope, or other browser-backed test was changed. The
detailed classification and ROI decision are recorded in
`note/test_runtime_phase3d_assessment.md`; no broader Phase 3D rollout is
currently justified.

The follow-up maintenance correction leaves `_initialize_strict()` timing
arguments unset by default and applies instance overrides only when explicitly
provided. The current verification passed 26 BookWalker Adapter cases, 129
Integration cases, and 822 full-suite cases; collection is Unit 624 /
Integration 129 / Research 69 / Total 822. This correction makes no new
runtime claim and does not change production defaults or test semantics.

## 1. Scope

Coreはサイト固有DOMやページ送りを判断しない。共通処理を担当する。

主な責務:

- Playwright browser/context接続補助
- URL navigation
- Site Adapter呼び出し
- PageState loop
- capture / artifact保存（default PNG、Adapter direct captureではformat metadataを保持）
- SHA-256 fingerprint
- duplicate / same-content guard
- manifest / progress
- diagnostics
- max_pages / retry / timeout
- 正常終了後のZIP packaging

Site固有selector、END判定、NEXT操作は `site_adapters/<site>/` の責務。

## 2. Main modules

```text
src/screenshot_crawler/core/
├─ browser.py       browser launch / CDP endpoint / CDP connection / session
├─ capture.py       Locator / canvas capture, artifact save
├─ diagnostics.py   screenshot / HTML / metadata / error
├─ errors.py        crawler errors
├─ fingerprint.py   SHA-256
├─ models.py        RunConfig / identity / context / captured page
├─ packaging.py     manifest-based ZIP / library output
├─ progress.py      manifest / progress / new-run safety
├─ runner.py        state machine
└─ state.py         PageState
```

`site_adapters/base.py` がAdapter contract。

## 3. Browser Session Model

### 3.1 採用済みの目標仕様

Real-site automationは、1つの共通Crawler Chrome/profileへCDP接続し、そのChromeをPlaywrightで操作する。

```text
Crawler Chrome
└─ .chrome-crawler/
      ├─ bookwalker.jp session
      ├─ manga-one.com session
      └─ other site sessions
          ↑
          │ CDP
          ↓
Playwright Browser / Context / Page
          ↓
Core Runner
          ↓
Site Adapter
```

役割:

- CDP = Chromeへの接続transport
- Playwright = 通常のbrowser/site操作API
- Adapter = site固有viewer logic

Raw CDP ProtocolはPlaywrightで代替できない場合だけ使う。

### 3.2 現行実装

real-siteの標準launcherは `scripts/start_crawler_chrome.ps1` である。repository root基準の
`.chrome-crawler/` profileを使い、default port `9222`でshared Crawler Chromeを起動する。
指定portに既存CDP listenerがある場合はChrome processのcommand lineでportとshared profileを確認する。一致すれば既存Chromeを再利用し、一致しない・確認できない場合は二重起動せずerrorで停止する。

起動時の `--user-data-dir` はquoteして渡す。起動後も `/json/version` 応答だけを成功条件にせず、同じprocess確認を再実行し、remote debugging portとshared profileの一致を確認してから成功メッセージを表示する。

```text
scripts/start_crawler_chrome.ps1
.chrome-crawler/
```

BookWalker/Manga ONEのshared-profile live verificationが完了しているため、real-site launcherはこの共通launcherのみを標準とする。移行前に作成されたsite-specific profile directoryが残っていても、launcherは自動削除しない。

現行CLIのendpoint解決も:

```text
--cdp-endpoint
→ site-specific *_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

で統一されている。CLI指定を最優先し、site-specific endpointは例外overrideとして
維持する。`.env`の値よりプロセス環境変数が優先される。

Phase 1/2では、次を実装済みである。

```text
CRAWLER_CDP_ENDPOINT
core.browser.resolve_cdp_endpoint()
core.browser.BrowserSession
```

`CRAWLER_CDP_ENDPOINT` はshared Crawler Chromeを指す標準global endpointである。
site-specific endpointは特殊なprofile/account等のための例外overrideとして残している。

既存CDP listenerがある場合、launcherはprocess command lineのremote debugging portと
`--user-data-dir`をshared profileと照合する。一致しない、またはprocessを確認できない場合は
既存Chromeを黙って再利用せずerrorで停止する。

### 3.3 移行時の非変更範囲

Browser Session統一のために以下を変更しない。

- BookWalker capture方式
- BookWalker END/NEXT_CONTENT
- Manga ONE capture方式
- Manga ONE image-disappearance END heuristic
- Runner fingerprint dedupe
- output/packaging semantics

Browser/session管理だけを差し替える。

## 4. Authentication model

login sessionのauthorityは共通Chrome profile。

Chrome自身がsiteごとに:

- Cookie
- localStorage
- IndexedDB
- その他browser storage

を保持する。

Crawlerはsite別storage-state JSONを標準管理しない。

login CLIは:

```text
Browser Session Layer
→ Playwright Page
→ site-specific login handler
```

で動く。

real-siteのcrawl/loginは `BrowserSession.connect()` でCDP接続し、既存の
BrowserContextからPageを作成する。crawlが作成した作業Pageは終了時に閉じる。
loginは別siteの既存タブを再利用せず、常にlogin用new Pageを作成して終了時に閉じる。
BrowserSessionの終了はPlaywright接続を切断するだけで、remote Chrome processは閉じない。

Probeのnative Playwright launchでは `launch_browser()` / `create_browser_context()` を使う。
`connect_browser()` と `close_browser()` はProbeおよびBrowserSessionで使うため残している。
repository-wideでcall siteがなかった `BrowserSession.existing_page()` と `create_page()` は削除した。
保存済みauth-stateの補助 (`auth.storage` / `save_auth.py`) もProbe・local auth workflowで到達可能なため、
real-site標準がChrome profileであることだけを理由に削除しない。

credentialsのinputは `.env` 等を使ってよいが、session保存はChromeへ任せる。

CAPTCHA / MFA / validation errorは自動突破しない。

## 5. CDP endpoint policy

現行の優先順位:

```text
--cdp-endpoint
→ <SITE>_CDP_ENDPOINT
→ CRAWLER_CDP_ENDPOINT
→ http://127.0.0.1:9222
```

通常はglobal endpointだけを使う。

site-specific overrideは例外用:

- 別account
- extension差
- browser setting差
- session分離
- 共通profileでは正常動作しない場合

## 6. Adapterとの境界

Adapterへ渡るものはPlaywright `Page`。

Adapterは:

- Locator取得
- click / keyboard / mouse
- wait
- evaluate
- capture target決定
- END / NEXT_CONTENT判定

を行う。

Adapterは:

- Chrome launch
- profile選択
- endpoint解決
- `connect_over_cdp()`
- BrowserContext lifecycle

を行わない。

## 7. PageState loop

PageState:

```text
CONTENT
AD
END
NEXT_CONTENT
LOADING
UNKNOWN
```

Runner概念フロー:

```text
ensure output dir is new/empty
prepare_page
page.goto
adapter.initialize
initial context
ProgressStore作成

loop:
    detect state

    END / NEXT_CONTENT
        -> normal return

    UNKNOWN
        -> error + diagnostics

    AD
        -> go_next + wait_for_change

    CONTENT
        -> max_pages guard
        -> context確認
        -> identity取得
        -> one/multiple capture targets取得
        -> capture
        -> fingerprint dedupe
        -> artifact bytes + manifest/progress保存
        -> go_next + wait_for_change
```

LOADINGはbounded retryし、解消しなければ `PageChangeTimeoutError`。

## Adapter timeout layering

`RunConfig.page_change_timeout_ms` is the adapter-owned operation deadline. The
Core `CrawlerRunner._adapter_call()` wrapper uses the adapter deadline plus
`adapter_timeout_grace_ms` (default 2,000 ms). Adapters may override
`get_initialize_timeout_ms()` when initialization sequences multiple bounded
phases; the base implementation returns the usual page-change budget, so other
adapters retain their existing timeout. Magapoke uses a larger bounded outer
budget for access readiness, click confirmation, and viewer stabilization.
Page-change waits still use their original per-phase budget, and the grace
applies to all adapter calls.

## 8. max_pages

`max_pages` は保存ページ数の安全上限。

重要な境界仕様:

- `saved == max_pages` のあと次stateが `END` / `NEXT_CONTENT` → 正常終了
- `saved == max_pages` のあとさらに `CONTENT` → `MaxPagesExceededError`
- `max_pages`を超えるPNGは保存しない

## 9. Identity / fingerprint / duplicate

`ContentIdentity` はpage id / page number / source id等を保持し、主に:

- Adapter change detection
- manifest
- debug / progress

へ使う。

**保存duplicateのauthorityはcapture bytesのSHA-256 fingerprint。**

identityが異なっていてもfingerprintが同一ならduplicate扱い。

これは既存BookWalker / Manga ONEの動作互換を優先した現行仕様。

## 10. same-content guard

新しいcaptureが得られない状態が続いた場合は `same_content_count` を増やす。

既定 `max_same_content = 3`。

上限到達で `PageChangeTimeoutError` として停止する。

## 11. Context / NEXT_CONTENT

開始時 `ContentContext` と現在contextのstrong fieldを比較する。

strong fields:

- content_id
- work_id
- episode_id
- chapter_id

同じfieldが開始時・現在とも存在し、値が変わった場合だけcontext change。

optional情報が後から埋まっただけではNEXT_CONTENTにしない。

## 12. Capture

基本はLocator単位capture。

Canvas targetの場合、`capture.py` はcanvas raw PNG bufferを取得できる。
`toDataURL()` がtainted canvasの `SecurityError` やPlaywright evaluate errorで
失敗した場合は、同じLocatorの `screenshot()` へsite-neutralにfallbackする。
これによりcross-origin画像を描画するcanvasも、viewer外を撮らずに保存できる。

Adapterは `get_capture_targets()` で複数targetを返せる。保存順はAdapterが返した順。

一時targetは `cleanup_capture_targets()` で後始末する。

Adapterは必要な場合だけ `capture_page(page)` をoverrideできる。非`None`の非空
`tuple[CaptureResult, ...]`を返した場合、CoreはLocator captureを行わず、その結果を同じ
fingerprint / manifest / page dimension処理へ渡す。`None`、`CaptureUnavailableError`、Coreの
bounded timeoutでは従来の `get_capture_targets()` → `capture_locator()`へfallbackする。
fallback後のcapture失敗は通常のrun errorとし、直接capture hookが作ったtemporary resourceの
cleanupはhook側の責任とする。Base Adapterは`None`を返すため、overrideしないsiteの挙動は維持する。

## 13. Run output safety

新規runの `output_dir` は、存在しないか完全に空でなければならない。

既存ファイルが1つでもある非空directoryは `RunAlreadyExistsError` で拒否する。

目的:

- 前runのcapture artifact混入防止
- manifest/progress上書き防止
- user file削除防止

`ProgressStore` も既存manifest/progressを暗黙上書きしない。

## 14. Manifest / progress

実行中:

```text
<output_dir>/
├─ page-0001.png  # default Locator capture
├─ page-0002.webp # source-native Adapter captureの例
├─ manifest.json
├─ progress.json
└─ diagnostics/  # failure時に作られる場合あり
```

manifestは保存ページ一覧のauthority。

各page entryは `mime_type` と `file_extension` を持つ。Locator / canvas captureの
defaultは `image/png` / `.png` で、Adapterのdirect captureはsource-native artifactの
formatをそのまま記録できる。Runnerはこのextensionで連番ファイル名を生成し、
packagingはmanifest記載の安全なJPEG/PNG/WebP artifactだけを対象にする。

`progress.json` はlast sequence / identity / fingerprint / contextを持つが、**自動resume機能ではない**。

JSON更新はtemporary file → `os.replace`。

## 15. Resume

現行ではresume未実装。

- 非空run dirは拒否
- 既存manifest/progressを読み込んで続行しない
- 暗黙resumeしない

将来追加するなら `--resume` 等で新規runと明示的に分離する。

## 16. Packaging

正常な `END` / `NEXT_CONTENT` 後だけZIP化する。

ZIP対象はdirectory globではなく `manifest.json` の `pages[].file` がauthority。

安全ルール:

- manifest外artifactをZIPへ入れない
- manifest記載artifact欠落はfail
- unsafe path拒否
- manifest file重複指定拒否
- 既存同名ZIPは上書きしない

ZIPはlibrary treeへ保存し、completion status JSONを別途残す。ZIP内部の画像は
manifestの`pages[].file`に記載された相対パスをそのまま使い、archive stemの
top-level directoryは作成しない。

Batch Candidateは必要な場合だけsite-neutralな`artifact_prefix`と
`artifact_disambiguator`をpackagingへ渡せる。`artifact_prefix`はpositionを
最小3桁で表すarchive filename全体の先頭prefixであり、metadataの`title` /
`order` / `author` / `genre`を変更しない。Batch Plannerの`order`は生の
`Item.order_label`を維持し、positionはshared `archive_position_prefix()`で
`BatchCandidate.artifact_prefix`へ分離する。labelなしはprefixだけになり、
positionがNULLなら従来のorder labelを維持し、positionを`order_key`やID等から
推測しない。Core packagingのprefixはarchive/status stemだけに作用し、library
directoryは従来どおりgenre/titleである。
Plannerはsite-scoped snapshotの全status Item/Sourceを対象に、既存の
`archive_stem()`でsanitized base stemを比較する。同一Work内でdistinct Item IDが
衝突するgroupのSourceだけへ`{site}-{Source.external_id}`を設定し、同一Itemの複数
Sourceだけではsuffixを付けない。Manga ONE/Magapoke専用のnaming workaroundは廃止した。
ZIP内部の画像はmanifestの相対パスをそのまま使い、作品stemのtop-level directoryは作成しない。
archive filenameとcompletion status JSONのfilenameは同じstemを使う。stemは
`artifact_prefix-[title if sanitized title length < 50]-order-author[-artifact_disambiguator]`
である。正規化・サニタイズ後タイトルが50文字以上の場合だけtitleを省略し、
title自体は常にlibrary directoryに含める。50文字ちょうども省略対象である。
filename要素がすべて空の場合は`archive`をfallbackにする。statusは
`output/crawl-status/<genre>/<title>/<stem>.json`へ保存し、Work間の同じstemでも衝突しないようにする。destination存在時の
`FileExistsError`と自動連番なしの安全性を維持する。既存archive/status/Artifact
locator is not changed by an ordinary Batch. Historical naming/status inconsistencies are
inspected only by `scripts/check_archives.py`; actual candidate-path occupancy remains a hard stop and is checked again after
crawl immediately before packaging. Explicit renumber remains a separate strict maintenance
operation for updating existing names and Catalog locators.

既存archiveのP4 renumberは `scripts/renumber_archives.py` が薄いCLI wrapperとして提供する。
`--work-key`、`--site`、両方のAND、または`--all`の明示scopeが必須で、defaultはdry-run、
変更は`--apply`時だけである。current ArtifactはSourceごとに、archive/zip Artifactを生成した
最新successful CrawlRunから最大1件だけ選ぶ。新しいsuccessful runにarchiveがなければ古い
successful runを探すが、選択後のlocator欠損では歴史Artifactへfallbackせず`MISSING`とする。
`display_position=NULL`、複数archive Artifact、非filesystem、locator欠損はそれぞれ安全にskipする。
old pathは常に`Artifact.locator`、new pathはそのparent内のP3 shared naming stemであり、
library treeのdirectory移動やZIP再走査は行わない。P3のsame-site Work/stem collision snapshotは
P4でもfiltered subsetではなく全site snapshotから計算する。

P4はscope全体を先にpreflightし、内部/外部target collision、collision dependency、status target
collisionを検出してoverwriteを拒否する。実行時はZIPを短い
`.archive-renumber-{artifact_id}.tmp`へ、matching status JSONを
`.status-renumber-{artifact_id}.tmp`へ移してからfinalへ移す二段階renameを使う。
rollback時も`.archive-rollback-{artifact_id}.tmp`と
`.status-rollback-{artifact_id}.tmp`を分離する。元の長いbasenameはtemp名へ含めない。
`output/crawl-status/<genre>/<title>/<old-stem>.json`はJSONの`archive_path`がold
Artifact locatorと同一fileを指す場合だけmatchingとする。明示的なrenumberは旧形式の
`output/crawl-status/<old-stem>.json`も後方互換で確認し、matching時だけrenameして`archive_path`のみ
更新する。missing/mismatch statusはwarningでZIP renameをblockしない。Catalog側は
`update_artifact_locators()`のcompare-and-set一括transactionでlocator/updated_atだけを更新し、
SHA-256、byte size、state、CrawlRun、Item、historical Artifactを変更しない。Catalog更新失敗時（SQLite由来を含む通常の
Python例外）はZIP/statusを二段階rollbackし、成功時は明示ERROR、失敗時は`RECOVERY_REQUIRED`と復旧pathを報告する。
実Catalogや実archiveへの`--apply`は未実行である。

既存ZIPの移行用に、`scripts/flatten_zip_archives.py`を提供する。指定directory配下を
再帰検索し、画像artifactだけが同じ1つのtop-level directory配下にあるZIPから、その1階層だけを
除去して元ZIPを安全に置換する。flat済み、曖昧なtop-level、unsafe path、collision、破損ZIPは
変更せず、`--dry-run`ではFIX / SKIP / ERROR判定とsummaryだけを表示する。画像データは
読み書きするが、画像デコード・再エンコードやCatalog / crawler本体の更新は行わない。

## 17. Intermediate directory cleanup

ZIP作成後、source crawl directoryを削除するのは、directory内容が次だけの場合に限る。

- `manifest.json`
- `progress.json`
- manifest記載page artifact

余分なartifact、diagnostics、user file、その他directoryがあればsource全体を `rmtree` しない。

失敗runは残す。

## 18. Diagnostics

現在の `write_diagnostics()` が保存するもの:

```text
screenshot.png
page.html
metadata.json
error.txt
```

既知の制約:

- diagnostics pathはrun-specific subdirectoryを自動生成しない
- `SiteAdapter.collect_debug_metadata()` is collected into failure diagnostics under
  `adapter_debug`; confirmed grant-only runs additionally write the generic
  metadata-only `diagnostics/entry_trace.json`.
- diagnostics保存失敗は元例外を隠さない

## 19. CLI / packaging flow

The crawl CLI closes the worker Page and disconnects the Playwright/CDP
session before running the filesystem-only `package_crawl_output()` step. This
keeps delayed browser events from writing to a transport that is already being
torn down. The remote Crawler Chrome process itself is never closed.

現行real-site crawl:

```text
CLI
 -> endpoint resolution
 -> BrowserSession.connect()
 -> existing BrowserContext
 -> crawler/login Page
 -> CrawlerRunner.run
 -> END / NEXT_CONTENT
 -> crawler Page close
 -> package_crawl_output
 -> Crawler Chromeは残す
```

主なcrawl引数:

```text
--site
--url
--output-dir
--diagnostics-dir
--library-dir
--max-pages
--max-same-content
--access-strategy auto|direct|quota
--title
--author
--order
--genre
--env-file
--cdp-endpoint
--keep-open
```

2026-09-17時点で、`access_strategy` とoutput metadata override用のCLI/API inputは実装済みである。manual crawlのdefaultは`auto` + metadata未指定で、従来のURL-only挙動を維持する。

現行のRunConfigは、概念上のCrawl Request入力として次を保持する。

```text
access_strategy = auto / direct / quota
optional output metadata:
  title
  author
  order
  genre
```

手動crawlのdefaultは `auto` + metadata未指定とし、現行挙動を維持する。

## 20. Tests

Unit testsで主に確認するもの:

- fingerprint
- capture
- Runner guards
- max_pages境界
- duplicate / same-content
- progress safety
- packaging / manifest validation
- site parser/helper

Browser Session共通化で現在確認しているもの:

- endpoint precedence（CLI > site override > global > default）
- BookWalker / Manga ONEが同じresolverを使うこと
- shared context/page取得
- remote Chromeをcloseしない
- login/crawl共通BrowserSession
- Adapterがbrowser接続方式へ依存しない

2026-09-17にshared `.chrome-crawler/`でBookWalker/Manga ONEのlogin・crawl・session共存を確認済みである。
loginは既存tabを再利用せず専用new Pageを使い、Pageだけをcloseしてremote Chromeを維持する。
両siteのcapture・navigation・END behaviorに回帰はない。

## 21. Known maintenance items

- `BrowserSession`の不要Page helper再発防止
- explicit resume
- diagnostics run directory分離
- config.yaml整理
- identity/fingerprint dedupe再検討
- GitHub CI
- tracked `.egg-info` 整理

これらを変更した場合は、このnoteを必ず更新する。

## Catalog v6 base plan: display position / archive naming / status expansion (runtime v7)

**P1-P4 IMPLEMENTED; P5 COPY-ONLY VERIFICATION / OPERATIONAL ROLLOUT REMAINS.** The adopted implementation plan is:

```text
note/07_catalog_position_archive_plan.md
```

The plan bundles Source-scoped display positions, position-prefixed archive naming,
existing-archive renumber tooling, and Item status expansion
(`pending | completed | skipped | external`) plus `items.note`.
Catalog schema v6, the Item status/note service and CLI, Source display-position
storage/validation, v5 -> v6 migration, CSV export fields, Discovery position
assignment, and P3 position-prefixed Batch archive naming are implemented.
Existing archive renumbering, current Artifact locator updates, and safe matching
crawl-status JSON rename are implemented as the local-only
`scripts/renumber_archives.py` maintenance command. The later work-key extension
uses Catalog v7 and adds explicit acquisition-scope synchronization plus
cross-site archive order; see the current-state section above and the work-key
runbook. P5 validates working copies and synthetic archive transactions; no
real Catalog/output migration or renumber has been applied.
P4 temporary sibling paths use short Artifact-ID-based names without copying the
archive basename, so long Windows archive paths can complete the two-stage rename
and rollback without hitting the legacy path-length limit.

## 22. Discovery / Catalog / Batch（Watchlist + Catalog + Discovery + Batch v3実装済み）

2026-10-02時点では、Watchlist + Catalog基盤、Crawl Requestの最小基盤、site-neutral Discovery framework、Comic DAYSを含む各siteのDiscovery / Site Policy registry、Phase 5Aのread-only Batch Planner、Manga ONE・BookWalker Batch Executor、BookWalker Adapterのstrict direct・quota product-page entryが実装済みである。Comic DAYSは公式free-only Atomの再検証を行うdirect専用Adapterとして登録され、ticket/point/coin/quota resourceは扱わない。BookWalkerは05:00 JSTのsite-wide 1枠local safety policyを使い、quota開始をreader entry前に永続化する。実サイトquota clickは未確認である。

Comic DAYSのC3実サイトE2Eでは、明示的な`catalog_comicdays.sqlite`と隔離watchlistを使い、登録済みDiscoveryが79件（free 4 / unknown 75）をCatalogへ同期した。通常のBatch Plannerはfree targetをdirect・`consumes_quota=false`で選択し、登録済みBatch ExecutorがCrawlerRunner、packaging、CrawlRun / Item / Artifactの成功確定まで完了した。実行結果は32 native PNG、area 1..32、`END`、CRC・manifest fingerprint・dimensions一致である。通常の`catalog.sqlite`とroot `watchlist.yaml`はこのE2Eの入力にしていない。

The dated Japanese C3 paragraphs immediately above are historical snapshots.
Their direct-only/free-only and no-ticket statements are stale and must not be
used as the current contract; the current behavior is the non-deferred,
one-Catalog-candidate Work Ticket flow below.

### Current Comic DAYS Batch authority

The older C3 paragraph above describes the former free-only implementation and
is historical. Current Comic DAYS Discovery full classifies the complete
first-party listing, and `quota_limit=1` keeps one Work Ticket candidate per
work in existing Catalog order. Quota execution is non-deferred: the adapter
does not run a live candidate resolver, opens the Planner-selected target once,
validates its target-local identity and exact Work Ticket contract, confirms
positive debit/unlock evidence, and continues normal crawling on the same Page.
Catalog/live identity or contract disagreement stops the resource pass with
`comicdays_discovery_refresh_required`; `isCharged=false` is the separate
`work_ticket_cooldown` state. The generic resolver remains for Zebrack, whose
Discovery cannot classify native per-chapter ticket state.

authority:

- `docs/SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/DISCOVERY_AND_BATCH.md`
- `docs/DECISIONS.md`

### 22.1 Watchlist（実装済み）

`WatchlistService`（`src/screenshot_crawler/watchlist/`）がhuman-managed `watchlist.yaml`を扱う。既定pathはcurrent directoryの`watchlist.yaml`で、CLIの`watch`配下では`--watchlist`でoverrideできる。schemaは`targets` listとrequired `key` / `work_key` / `site` / `url` / `label`、optional `enabled`（default `true`）である。required textは空文字を許さず、keyはlist内で一意で、duplicate・malformed YAML・不正targetは明示エラーにする。

同一Serviceでは内容が同じ間だけ検証済みtargetを再利用する。呼び出しごとにファイル本文を
読み、mtime/sizeだけでは判定しない。変更時は通常どおりparse/validateし、不正YAMLや
読み取り失敗時に古い結果へfallbackしない。返すlistは毎回別で、immutableなrowだけを共有する。

CLIは`watch list`、`watch add`、`watch remove`、`watch enable`、`watch disable`を提供する。書き込みは同一directory内のtemporary fileをfsyncして`os.replace`する。Watchlist操作はCatalogを読み書きせず、remove/disableでもCatalog rowを削除しない。

### 22.2 Catalog（Schema v7 P1実装済み）

P1 export detail: `items.csv` includes `note` and `sources.csv` includes
`display_position`; NULL values are emitted as empty CSV fields. P2 adds the
atomic `CatalogService.set_source_display_positions()` API. It validates all
positions and Source identities for `(site, discovery_key)` before updating all
rows in one transaction and refreshing `updated_at`; empty assignments are a
no-op and duplicate numeric positions are permitted.

`CatalogService`（`src/screenshot_crawler/catalog/`）がSQLite connection lifecycle、foreign key enforcement、schema initialization、v7 CRUDを集約する。既定DB pathは`catalog.sqlite`で、`initialize()`または最初のservice operationで初期schemaを作成する。通常のCatalogService / Discovery / Batch / Exportはunsupported schemaをmigrationせず拒否する。v3 / v4 / v5 / v6からの更新は明示的な`catalog migrate`で行う。

Schema v7は従来の7 domain tableに`acquisition_scope_sync`、`discovery_inventory_evidence`、`discovery_inventory_positions`を加える。`sources.acquisition_enabled`は`INTEGER NOT NULL DEFAULT 1 CHECK (0, 1)`で、既存Source履歴を保持したまま取得担当範囲を表現する。Workがstableな`work_key` / title / author / genreを保持し、ItemはWork配下の取得単位として`item_title`、kind、order、status、genericなoperator noteを保持する。`items.status`は`pending | completed | skipped | external`で、通常Batchの候補は`pending`だけである。`completed`以外へ変更すると`completed_at`はNULLになり、`completed`では取得時刻を設定できる。Artifactの移動・missing・deletedではpendingへ戻さない。v6→v7 migrationは全既存Sourceを`acquisition_enabled=1`にし、Scope sync/evidenceは未設定のままにするため、migrationのみで取得状態やZIP locatorを変更しない。

`Source`のidentityは`(site, external_id)`で、access stateとquota local stateを分離する。`update_source_external_state()`はquota stateを変更せず、`record_quota_access()`はquota stateだけを更新し、`clear_quota_access()`は指定timestampとのcompare-and-setが成功した場合だけquota stateをNULL化する。`mark_sources_unavailable_except()`は指定Discovery scope内のmissing sourceだけをunavailable化する。

`source_targets`はopaqueな`backend` / `target_key` / `locator`を保持し、identityは`(source_id, backend, target_key)`である。`CatalogService`はcreate/upsert/find/get/listを提供するが、target selectionやlocatorの解釈は行わない。

`crawl_runs`はItem/Source/Targetの整合性を検証して作成時snapshotを保存し、`running -> succeeded|failed`だけを許可する。`artifacts`はbinary本体を保存せず、SHA-256、byte size、storage backend、locator、stateを保持する。手動importのためcrawl runなしを許容し、Artifact更新はItem/CrawlRun statusを変更しない。

Phase 1でCatalog packageをv3へ移行し、Phase 2でWatchlist / DiscoveryをWork-aware化し、Phase 3でBatch Planner / ExecutorをCrawlRun / Artifactへ接続した。Phase 4ではCatalog Exportを6 CSVのread-only snapshotとして実装した。

Batch Planner用に `read_works_items_sources_and_targets(site=...)` を提供する。これはread-only接続でWork / Item全件、指定siteのSource、関連するSourceTargetを取得し、Plannerはraw SQLiteへ直接アクセスしない。`site=None`では全siteのSource/Targetを同じread-only snapshotで取得でき、P4 maintenanceの`--all` scopeに使う。指定siteのSourceを1件以上持つItemだけをsite-scopedな母集団にし、別site専用Itemとsourceなしのorphan Itemを`no_source` skipに含めない。未存在・未初期化Catalogを作成せず、Batch planによるCatalog副作用を防ぐ。

Catalog確認用に `catalog export` CLIを提供する。`catalog/export.py` の `export_catalog_csv()` はSQLiteをread-onlyで検証・読み込みし、`catalog-export/` 配下へ `works.csv`、`items.csv`、`sources.csv`、`source_targets.csv`、`crawl_runs.csv`、`artifacts.csv` の6 CSV snapshotを出力する。各CSVはtable identityとforeign keyを保持し、履歴をflat JOINで直積化しない。CSVはUTF-8 BOM、header付きで、NULLは空欄、`available` と `enabled` は `true` / `false` とする。既定pathは入力 `catalog.sqlite`、出力directory `catalog-export` であり、既存snapshotを上書きせず、CSVからCatalogへ戻す機能はない。

`catalog item-status <item_id> [pending|completed|skipped|external]` CLIはstatus省略時にItemの現状を表示し、指定時は`CatalogService`経由で状態を変更する。`catalog item-note <item_id> "text"` はnoteをset/updateし、`--clear`はnoteだけをNULLに戻す。status/note操作はCrawlRun / Artifactを作成しない。Discovery refreshはoperator-maintainedなstatus/noteを上書きしない。Batch Plannerは`pending`だけを候補にし、通常crawl成功後も既存の`mark_item_completed()`が使われる。

日時は`catalog.service.now_jst()`で生成するaware fixed-offset JST timestampを、ISO 8601の`+09:00`文字列として保存する。naive datetimeは拒否する。通常runtimeはschema v7だけをサポートし、異なるversionは暗黙migrationせず明示的に失敗する。v7ではdomain/scope tables、required columns、foreign key、Item status / Source position / acquisition flag constraintsを検証する。`catalog/backup.py`はschema-neutralなSQLite online backup、WAL-safe standalone化、quick_check、overwrite拒否を提供する。`catalog/migrations.py`は明示`catalog migrate`用のsequential v3→v4→v5→v6→v7 runnerを持ち、migration前automatic backup、single-transaction rollback、final validationを行う。

採用した上位flow:

```text
watchlist.yaml
    ↓
Discovery Service / Discovery Adapter
    ↓
    catalog.sqlite (works / items / sources / source_targets / crawl_runs / artifacts)
    ↓
Batch Runner / Site Policy
    ↓
Crawl Request
    ↓
既存CrawlerRunner
```

現行実装には、BookWalker quotaの実サイトlive click検証と、quotaのサーバー側実消費をCatalogだけから検証する機能は存在しない。

Watchlist CLI、Catalog Service、Work-aware Discovery framework、Crawl Request最小基盤、Schema v7 Batch Planner / Executor、Site Policy registry / Manga ONE・BookWalker・Piccoma Policyは実装済みである。Discoveryはtargetの`work_key`でWorkをfind/createし、`label`は新規Workのtitle初期値にだけ使う。新規recordはWork配下にItem、Source、web/default targetを原子的に作成し、既存recordはItemを再利用する。Batch PlannerはWork metadataとItem order metadataからcandidateを生成し、enabledなweb targetを`priority ASC, target.id ASC`で選ぶ。Batch Executorはstale validation後にCrawlRunを作成し、quota記録、Crawler、packaging、Artifact / Run / Itemの成功確定を順序づける。現行CrawlerRunnerへCatalog read/writeは追加せず、1 URL -> 1 run責務を維持する。

主要仕様:

- Discovery対象は明示Watchlistだけ
- Watchlist targetはstable `key` と明示的な `work_key` / `label` を持つ
- Catalog v3 Phase 5は `works / items / sources / source_targets / crawl_runs / artifacts` の6テーブルをauthorityとする
- full syncはcomplete時だけmissing sourceをunavailable化
- 現行incremental実装はlatest側から異なるknown source 2件連続で停止し、同一stable identityの重複観測はstreakに加算しない
- 採用仕様ではdefault known-streakを維持しつつ、site固有access遷移に必要なstable boundary hookを許容する。BookWalker Discoveryはこのhookを利用する
- 別site同一作品は自動mergeせずwarning only
- access modeは `owned / free / quota / paid / unknown`
- quotaは基本crawl開始時に消費記録
- site上に再閲覧猶予がある場合は `access_granted_until` で扱える。BookWalkerはsource単位grantを仮定しない採用仕様
- Batch/Site Policyが今回の `access_strategy` を解決する
- quota sourceでもactive grant中は `direct`、新規枠を使う場合だけ `quota`
- quota limit/reset ruleそのものをCrawlerへ渡さない
- Crawlerはtitle/author/order/genreをoptional inputとして受け取れるようにする
- metadataはfield単位で `explicit request > adapter > packaging fallback`
- metadata未指定なら現行Adapter自動取得を維持する
- crawl + packaging成功時だけArtifact(present)、CrawlRun(succeeded)、Item(completed)を1 transactionで確定

Phase 5AのBatch Plannerは `pending` itemだけを対象にし、completed / unavailable / paid / unknownをskipする。source priorityは期限付きfree、通常free、owned、quota、paid/unknownの順で、同順位はsource.id ASC。複数のquota-consuming candidateが新規枠を必要とする場合、quota仮予約の順序は`source.discovery_key`ごとのDiscovery groupをgroup内最小source.id（Catalog登録順）で並べ、group内を`order_key`のnatural orderで並べる。`order_key`を解釈できない場合は`order_label`、最後にitem.idのstable fallbackを使う。`discovery_key = NULL`のcandidateは明示groupの後ろに置く。free、owned、active grant中のquota sourceはdirectのままでこのquota allocation順序に入らない。Catalog metadataは`Work.title -> title`、`Work.author -> author`、`Work.genre -> genre`、`Item.order_label -> order`を従来どおり写し、positionは`archive_position_prefix(Source.display_position) -> artifact_prefix`へ分離する。positionがある場合は最小3桁のfilename prefix、NULLの場合はprefixなしとし、`order_key`やIDから補完しない。Batch Plannerはsite-scoped snapshotの全status Item/Sourceを対象に、`archive_stem()`後のsanitized base stemを同一Work内で比較し、distinct Item IDが複数のgroupだけへ`{site}-{Source.external_id}`を設定する。同一Itemの複数Sourceはcollision扱いしない。Manga ONE/Magapoke固有のsuffix workaroundは廃止した。

Manga ONE Policyはsite-wide local quotaを4枠、09:00/21:00 JSTのhalf-open window、24時間grantとして扱う。current window内の`quota_started_at`だけを数え、active grant（`access_granted_until > now`）はdirectでslotを減らさない。quota candidateはplanner内だけで仮予約し、Catalogは変更しない。手動・外部clientの実消費はCatalogから観測できない。

CLIは `batch plan --site mangaone --catalog catalog.sqlite` と `batch run --site mangaone --catalog catalog.sqlite` を提供する。`batch plan`はread-onlyで、`batch run`はcandidateをsequentialに実行し、quota stateをCrawler開始直前に保存し、crawl + packaging成功後だけcompletedを更新する。`--limit N`は先頭N件に制限し、失敗時は後続を実行しない。

BookWalker Discoveryはseries listから商品URLを列挙し、商品ページのreader controlを観測してCatalogへ反映する。BookWalker Site Policyはsite-wide 1 quota / 05:00 JST half-open windowを評価し、`access_granted_until`をdirect判定に使わない。Batch Executorはquota candidateの`quota_started_at`をCrawler開始前に保存し、`access_granted_until=NULL`を許容する。同一window内の失敗はrefundせず、Executorの現在Catalog再検証で同一candidateをCrawlerへ再投入しない。Manga ONEの24時間grant挙動は維持する。実サイトquota clickは自動検証していない。

誤ったlogout状態のBatch実行などで、実際のreader消費ではなくCatalog上の予約だけを戻す必要がある場合は、`scripts/restore_bookwalker_quota.py`を使う。既定はdry-runで、`--crawl-run-id`（failedかつquotaのCrawlRun）または`--source-id` / `--external-id`を指定し、`--apply`時には先にverified SQLite backupを作る。修復対象は`quota_started_at`と`access_granted_until`だけで、`access_mode`、CrawlRun、Item status、Artifactは変更しない。これはBookWalkerサーバー側の10分利用を巻き戻す機能ではない。executor実行中の同時修復は避ける。

### 22.3 Discovery framework（実装済み）

#### Current incremental known-streak threshold

The current generic incremental Discovery implementation stops after five
consecutive distinct known source identities. Observing a new source resets
the streak to zero. Any older two-known-source examples in this historical
note describe the former default and are superseded by the current value.

#### P2 Discovery position assignment

`DiscoveryService` retains the first-observed Source IDs in Adapter yield order
as a run-local ordered set. The Adapter remains responsible for canonical
newest-to-oldest Discovery order. A bounded-capable Adapter also attaches a
run-local `global_display_position` hint after observing the complete listing
and before applying its scope slice. The hint is not persisted separately.

`Source.display_position` means the 1-based position in the site's complete
work listing ordered oldest-to-newest. It is never inferred from episode
labels, numeric IDs, `order_key`, `order_label`, or publication dates. Bounded
Discovery filters synchronized Sources but does not renumber them: if the
complete listing positions selected are 4..7, Catalog receives 4, 5, 6, 7.
The Service validates hints (`int`, not `bool`, and `>=1`), rejects conflicting
Source/position mappings, and finalizes them only after safe completion.

Unbounded full Discovery retains the existing reverse of the canonical stream
to assign `oldest=1 ... newest=N`. Bounded full Discovery requires a global hint
for every observed Source and fails closed without one; it never falls back to
scope-local `1..N`. Incremental Discovery uses a complete available global hint
as the authority. `DiscoveryAdapter.allow_inferred_display_positions` defaults
to `True`, preserving existing fallback behavior. An Adapter may set it to
`False` to suppress no-hint inference in full, exhausted incremental, and
early-stopped incremental runs; established positions then remain unchanged and
new Sources remain NULL. Complete validated global hints still apply when this
option is `False`. Bounded incremental Discovery still requires a complete
global hint for every observed Source and fails closed without one; it never
uses inferred or scope-local positions. Incomplete runs never finalize
positions or rewrite established positions; newly created Sources may remain
NULL.

Position finalization uses only records already yielded by the existing
Discovery run; it adds no pagination, DOM, HTTP, or full-list access. Discovery
position updates do not modify Item status, `completed_at`, or operator notes.

#### Magapoke M3b Batch boundary

Magapoke Policy allows free sources with `direct`. A quota source is eligible
only when Discovery observed a future `access_granted_until`, in which case it
uses `direct`, `reason="active_rental"`, and `consumes_quota=False`; all other
quota, paid, unknown, and unverified owned sources are skipped. Discovery reads
the renting countdown only within the matching episode row. The displayed
`あとNN時間` is floored human text, so the recorded `access_granted_until` is
an observation-time lower bound, not an exact rental expiry. A later non-NULL
observation refreshes that field; NULL preserves the stored grant. Discovery
does not write `quota_started_at`. There is no schema change, quota capacity,
ticket consumption, or site-specific Planner/Executor behavior. Adapter entry
remains `auto`/`direct`; quota entry remains rejected.

`DiscoveryService`（`src/screenshot_crawler/discovery/`）は、呼び出し元が用意したPlaywright Page、enabledな`WatchlistTarget`、`full`または`incremental` modeを受け取る。Chrome launch、CDP endpoint、profile、Browser Session lifecycleはServiceやDiscovery Adapterに持たせない。targetの`work_key`でWorkをfind/createし、Work titleは新規作成時だけ`label`から初期化する。author/genreは観測値が非NULLでWork側がNULLの場合だけ補完し、既存値を上書きしない。

`DiscoveryAdapter.iter_records()` yields site-neutral `DiscoveredRecord` values. Adapters do not access Catalog; the service injects `site` and `discovery_key` from the target. Current real-site adapters include Manga ONE, BookWalker, Magapoke, and Piccoma. Piccoma supports episode-list Discovery, fresh-free viewer/capture, and an available+free-only direct Batch Policy. Synthetic local Batch integration and the two-product live Discovery-to-ZIP route passed. The Phase 06-B PNG E2E is historical; Phase 06-D independently verified the current lossless WebP output through the standard Batch-to-ZIP path for all 39 pages in the two selected episodes, with six current Core RGB comparisons matching exactly. Other layouts/resources and unobserved draw/backdrop variants remain unsupported. BookWalker Discovery accepts Watchlist series-list targets only.

Discovery Serviceは各recordについて、canonical titleをItemへ保存せず、kind/orderをItemへ、title/author/genreをWorkへ反映する。新規recordではItem/Source/web-default targetを一つのtransactionで作成し、既存sourceでは既存Itemを再利用して外部状態と非NULL Item metadataだけを更新する。観測した`DiscoveredSource.url`は`SourceTargetInput(backend="web", target_key="default", locator=...)`として同じsourceへupsertする。URL変更は同じ`(source_id, web, default)` targetのlocator更新になり、既存androidやweb/direct等の別targetは変更しない。sourceのfull-sync missing reconciliationは`available=false`だけを更新し、targetの削除や自動disableは行わない。既存sourceの`discovery_key` scope不一致、または既存Itemが別Workに属する場合はincompleteとして扱い、reparentや部分的な新規graph作成を行わない。

Discovery開始時、Serviceは対象siteの既存sourceからCatalog非依存の
`DiscoverySourceSnapshot`を一度だけ作成し、adapter hookへ渡す。このsnapshotはrun開始時点をauthorityとし、run中に新規upsertされたsourceを既存sourceとして扱わない。
`DiscoveryAdapter.reconcile_access_mode()`は観測したaccess modeだけをsite-specificに調整でき、defaultは観測値をそのまま返す。`incremental_stop_decision()`は
`DEFAULT` / `CONTINUE` / `STOP`を返し、defaultでは従来のknown source 2件連続停止を使う。`STOP`はrecordのupsert後に`stable_boundary`で終了し、full modeではstop hookを呼ばない。両hookからの`DiscoveryIncompleteError`は既存のincomplete semanticsに従う。

fullはiteratorの正常終了だけを`complete=true`とし、`DiscoveryIncompleteError`または予期しない例外ではmissing sourceのreconciliationを行わない。complete fullだけが同じ`site + discovery_key` scopeの未観測sourceを`available=false`にする。現行incrementalのknown判定と2件連続streakはServiceが管理し、2件目をrefreshしてから停止する。未観測sourceはunavailableにしない。

BookWalkerはこのextension pointを実装し、run開始時点でowned/quotaだったsourceをstable boundaryとして扱う。既存owned/quotaのaccess stateは、商品ページの観測がpaid/unknownへ揺れた場合も保持する。Manga ONEはhookをoverrideせず、従来のknown-streak挙動を使う。

### 22.4 Discovery CLIの複数target同期（実装済み）

`discover` は `--key KEY`、`--site SITE`、`--all` のmutually exclusive required
groupを持つ。`--key` は従来どおり1 targetを処理する。`--site SITE` は
`WatchlistService.list_targets()` のfile orderから `target.enabled is True` かつ
`target.site == SITE` のtargetだけを選び、site名のalias変換は行わない。`--all` は
enabled target全件を同じ順番で選ぶ。disabled targetはDiscoveryServiceへ渡さない
ため、Catalogの既存stateは変更されない。`--all` の0件は
`No enabled watchlist targets.`、`--site` の0件は site名を含むメッセージを出して、
どちらも接続・Catalog初期化なしで正常終了する。

`--site` と `--all` ではtargetごとにendpointを解決し、`BrowserSession.connect()`、new Page、
既存`DiscoveryService.discover(page, target, mode)`、Page close、disconnectを
順番に行う。site-specific endpoint、global endpoint、defaultの既存優先順位と、
明示`--cdp-endpoint`の最優先を維持する。Crawler Chromeは自動起動しない。

各targetの結果（observed/new/known/complete/stopped_reason/warnings）とstatusを
表示し、失敗しても後続targetを続行する。例外failureに加えて
`DiscoveryResult.stopped_reason == "incomplete"`もtarget failureとして扱い、
`Discovery incomplete`を表示する。全target後にsummaryを表示し、`--site` ではsiteも
表示する。1件以上の失敗は`DiscoveryAllError`からCLI non-zeroへ変換する。全成功と
enabled target 0件は正常終了する。`--site --keep-open` と `--all --keep-open`は
target単位で接続を閉じるlifecycleのためCLI validationで拒否し、従来の
`--key --keep-open`だけを維持する。

cross-site duplicateは同じWork内の別Itemについて、kind/orderが一致する場合だけ候補をwarningにする。warningはmerge、reparent、delete、completed化を行わない。

### 22.5 Batch Planner / Executor（Schema v7、取得担当ゲート実装済み）

`BatchPlanner`（`src/screenshot_crawler/batch/planner.py`）はWork-aware read snapshotから
candidateを生成する。metadataは`Work.title` / `Work.author` / `Work.genre` / `Item.order_label`
から作り、Itemのorder fallbackは`order_key`、`order_label`、`item_title`、`item.id`の順である。
指定siteのSourceを持つItemだけを対象にし、Web targetだけを`priority ASC, target.id ASC`
で選ぶ。`BatchCandidate`には`backend` / `target_key` / `locator`をsnapshotする。

`BatchExecutor`（`src/screenshot_crawler/batch/executor.py`）はcandidateを1件ずつ既存
`CrawlerRunner`へ渡す。`CrawlerRunner`はCatalogを知らず、Batch側だけが`item_id` /
`source_id` / `target_id`とCatalog stateを扱う。

実行前にitemが`pending`であり、sourceのitem/site/access_mode/availableとtargetの
source/backend/target_key/locator/enabledがcandidateと一致することを確認する。backendはwebだけを
受け付ける。Policyのaccess decisionも再確認し、stale candidateはCrawlerを呼ばずに停止する。

Candidateから次の`RunConfig`を作る:

```text
site / source_url / access_strategy / output_metadata
output_dir = output/batch/<site>/item-<item>-source-<source>-<JST timestamp>-<uuid>
diagnostics_dir = <run directory>/diagnostics
```

実行はsequential、stop-on-first-failureである。candidate validation後、Crawler開始前に
`CrawlRun(running)`を作成する。quota candidateだけはその後に`record_quota_access()`を呼び、
Policyの`access_grant_until()`で計算したgrantを保存する。direct candidateはquota stateを
変更しない。保存後にcrawl、viewer、packagingが失敗してもquota stateはrefundしない。

Crawlerが`END`または`NEXT_CONTENT`で正常終了し、既存`package_crawl_output()`が成功した後、
archiveの存在を確認してSHA-256 / byte sizeを計算する。Catalogのnarrow helperがArtifact(present)、
CrawlRun(succeeded)、Item(completed)を1 transactionで確定する。Catalog更新失敗時も生成済みarchiveと
status sidecarは削除しない。Crawler、異常停止、packaging、archive検証、finalizeの失敗は
CrawlRun(failed)へ記録し、Itemはpending、Artifactは作成しない。

実行CLI:

```powershell
.\.venv\Scripts\python.exe -m screenshot_crawler.cli batch run `
  --site mangaone --catalog catalog.sqlite `
  --watchlist watchlist.yaml `
  --output-root output\batch --library-dir output\Books --limit 1
```

### 取得担当範囲の自動反映とBatch選択

Batch Plannerはsource→item→workを解決し、現在のCatalog flagsから候補を選ぶ。
Scope Reconciler snapshot、fingerprint、sync marker、listing proofはBatchでは読まない。
Watchlist scope編集直後や他keyのDiscovery失敗後でも、最後に反映したflagsで取得を続ける。
Watchlist省略時にCatalog sourcesがあればfail-closedする。WatchlistにないWorkはskipする。
実Work/site identity不一致は拒否し、scope境界をBatch実行中にサイトへ問い合わせない。

`acquisition_enabled=0`はSite Policy評価前に除外され、skip reasonは`acquisition_disabled`。
ただしquota availabilityは候補絞り込み前の全Source履歴から計算し、以前の消費履歴を保持する。
有料/無料やavailable、Item status、Site Policyのaccess decisionと取得担当範囲は独立した判定である。

Normal、grant-only、deferred resolver、replan、追加resource passは同じflag判定を使う。
Executorはresolver/adapterを作る前にcandidateと実CatalogのWork/Item/Source/Target ID・external ID・
locator・enabledを照合し、Itemがpending、Sourceがavailableでcurrent access mode一致、flagが有効、
requested resourceが同一であることを確認する。`batch run`はCatalog job lockをplanningから終了まで
保持する。`--grant-only all`は全resource passをCDP接続前にpreflightし、全passが空ならBrowser/loginを
開始せず、execution直前にも各passをreplanする。

候補の再検証は`CatalogService.read_work_items_and_sources(work_id)`のread-only transactionで
対象Workの全site・全statusのItem/Sourceだけを読み、全Catalog/Target一覧を候補ごとに再取得しない。
resolver前のawaitを挟まない検証loopではWork単位で1 snapshotを共有し、async resolver/entryへ
そのsnapshotを持ち越さない。通常capture/grant-onlyの各entryと次のresolver呼び出しでは再取得する。
採番・同site内の命名衝突はExecutor内で直近1 Workの結果を保持し、Work metadata、Item ID/
Work ID/order_label、Source ID/Item ID/site/external_id/discovery_key/display_position/
acquisition_enabled、現Watchlist targetの完全一致時だけ再利用する。兄弟Sourceの追加・除外、
他siteの変更、採番/label/Watchlist変更は再計算する。status・grant更新は命名に影響しないため
再計算を起こさないが、candidateのpending/available/flag、identity/URL、Policy/resource stateと
capture保存先の衝突検査は毎回維持する。CLI/config/schema/pacingや権利消費契約の変更はない。

検証用Catalogコピーでの2026-10-24計測（Work 112、236候補、通信・保存先検査を除いた
entry前の検証部分）では、旧処理5候補3.87秒から全候補約182.8秒相当、修正後の全候補は
通常entry方式4.54秒、resolver pool方式2.59秒。旧全候補時間は推計であり、実サイトの所要時間
ではない。専用コピーと集計は`output/batch-validation-benchmark-20261024/report.json`。
通常captureでの連続成功後の再利用、resolverのWork単位読み込み、warm cache後のstale入力拒否、
cross-site兄弟変更、Watchlist編集/不正YAMLは人工fixtureで検証する。実サイトの権利消費は
この性能修正では未検証。

検証結果: Batch/Planner/Executor、Catalog、Watchlist、selected keys、deferred grants、CLIの
関連選択は**429 passed / 0 skipped**。最後のcache更新後のWatchlist/再利用回帰選択も
**57 passed / 0 skipped**。フルは**5,471 passed / 7 failed / 0 skipped**
（`output/pytest-batch-reuse-full.log`）。7件のうちHanayume 4件とpackaging 1件は長い
test出力pathでファイル作成に失敗し、短いworkspace内`--basetemp`で全5件PASS。
Comic DAYSの100ms deadline testはcancel event未観測のassertionで失敗したが、単独再実行は
PASS（全体実行時の原因は未確定）。残り1件は既存`crawler.yaml`のBookWalker delay=0msと
配布設定を期待するtestの200msとの差で、ユーザー設定を変更せず、HEAD配布設定の隔離コピーで
同一testがPASS。Ruffと変更差分のwhitespace検査はPASS。Integration/Researchはフルに含み、
実サイトの権利消費・live verificationはローカル検証処理だけの修正のため実行していない。

実行例:

```powershell
python -m screenshot_crawler.cli batch plan --site mangaone --catalog catalog.sqlite --watchlist watchlist.yaml
python -m screenshot_crawler.cli batch run --site mangaone --catalog catalog.sqlite --watchlist watchlist.yaml
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key my-work --dry-run --json
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --work-key my-work --apply --json
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --site comicdays --dry-run --json
python -m screenshot_crawler.cli watch scope-sync --watchlist watchlist.yaml --catalog catalog.sqlite --site comicdays --apply --json
```

Site-wide `watch scope-sync --site SITE` selects distinct work keys represented
by current Watchlist targets, including `enabled: false`; removed-key Catalog
Sources alone do not select a Work. Preview is aggregated and read-only. Apply
preflights every Work, holds the Catalog job lock, and preserves per-Work
transaction/CAS boundaries rather than claiming one site-wide transaction.
Failures report successful-return works, the stage-affected work, and
definitely unattempted works separately. `failure_stage` disambiguates the
failed key: preflight identifies a blocked Work not attempted; apply identifies
an attempted Work that may have committed before an exception; final validation
identifies the Work whose gate failed and may overlap the successful-return
list. After
per-Work synchronization checks, one final Watchlist snapshot compares both site
membership and each selected Work's complete key/scope/order fingerprint.

通常運用はDiscovery成功時に自keyのflagsを自動反映し、そのままBatchを実行する。
Discoveryなしの設定反映や全Workの厳密な整備には任意でscope preview/applyを使う。
scope-syncのapplyは従来どおり必要なFull listing proofを要求する。renumberは現在のflagsと順序を使う。Batch candidateのidentityや
現在計算したprefixが変化した場合はbatch plan/runを再実行する。

`batch plan`はCatalog flagsやquotaを変更せずread-onlyであり、`batch run`だけがquota local stateと
CrawlRun / Artifact / Item statusを書き換える。Manga ONEとBookWalkerのquota policyは既存挙動を
維持し、Android targetはCatalogへ保持できるがPhase 3 Executorでは実行しない。

### Catalog v6 / Magapoke M3c1 current update

Catalog schema v4 adds nullable sources.published_at and explicitly migrates v3 after an automatic pre-migration backup inside the existing transactional catalog migrate flow. Ordinary initialization remains non-migrating. Timestamp validation uses the same aware ISO/JST normalization as other Catalog timestamps.

Discovery passes DiscoveredSource.published_at into SourceInput; a non-NULL observation updates the Source, while NULL preserves the prior value. Magapoke parses the live-confirmed YYYY/MM/DD row date to JST midnight. This represents the site-observed publication day normalized for stable ordering, not an observed time of day. order_key remains site-neutral and Magapoke keeps it NULL.

Batch metadata now carries generic quota resource, scope, limit, and commit timing. Work-scoped quota limits are applied by grouping on Work.id; sources are ranked by published_at ascending with NULL last, then existing item ordering and stable source ID. Only work-scoped policies use the direct-first phase; Manga ONE and BookWalker retain their established site quota ordering. BatchExecutor passes quota_resource through RunConfig and commits after-observed consumption only when the Adapter reports a matching aware timestamp.

### Phase 4 current state: generic grant-only

Generic grant-only uses the existing adapter entry path with Core
`entry_only=True`. Work Ticket state is persisted in Catalog schema v7 as
Work/site/resource state, and confirmed consumption atomically updates that
state plus the source grant. Local cooldown skips happen before browser/page
creation; confirmed grant-only runs do not capture, package, or complete the
Item. Premium Ticket grant-only and policy-ordered `all` are implemented in
Phase 5; Premium balance remains live-only and is not stored in Catalog.
Normal Batch and grant-only share the observed resource-consumption persistence
helper; confirmed Work Ticket consumption updates source grant and Work state,
and later failure does not undo either update.
This Phase 4 section is the current implementation state and supersedes the
older Phase 3 planning sentence below.

### Phase 5 current state: Magapoke Premium Ticket and generic all

Magapoke exposes `work_ticket` then `premium_ticket` through the generic
grant-only contract. `--grant-only premium_ticket` uses the normal
`entry_only=True` Adapter path, reads the live semantic Premium Ticket balance,
respects Work Ticket priority, and fails closed on ambiguous UI. A clear zero
returns `premium_ticket_exhausted` and stops only that resource pass. Confirmed
Premium consumption persists the source grant through the Policy's conservative
71-hour `access_grant_until`; no Premium balance or Work-scoped resource state
is stored. `--grant-only all` replans Catalog between Policy-ordered passes,
shares its total site-attempt `--limit`, applies cross-pass pacing, and stops
the whole run for candidate site-operation errors or fatal AccessGuard errors.
Expected cooldown/resource-unavailable outcomes remain pass-local skips.
Grant-only leaves Items pending and creates no capture/package/Artifact.

### Phase 6 cross-site verification current state

The full automated regression suite has been run and is green across Magapoke,
Manga ONE, and BookWalker. It covers Phase 1 pacing and timeout isolation,
Phase 2 AccessGuard/metrics, generic resource passes, Work/Premium grant-only,
Catalog v6 migration, adapter retry/capture, and normal Batch semantics.
Read-only `batch plan` also passed for all three sites on a temporary v5 -> v6
Catalog migration copy. Actual normal live Batch and scarce Work/Premium
consumption were not forced because no safe non-consuming candidate/session was
available. The detailed matrix is `docs/PHASE6_VERIFICATION.md`; current status
is **AUTOMATED VERIFIED / LIVE PARTIAL**.

### Batch candidate failure and interruption current state

Batch site-operation errors are represented as candidate-scoped failures and
stop the sequential Batch after the current candidate is cleaned up. The
original underlying error type and message remain in the CrawlRun and metrics.
Expected cooldown/resource-unavailable outcomes continue as skips. AccessGuard
stops and Catalog/configuration errors remain Batch-fatal.

Operator cancellation is normalized to `BatchInterruptedError` with
`stop_reason=interrupted`. The active candidate is failed, no later candidate
starts, and the CLI exits with code 130. Confirmed resource consumption is
persisted before interruption is recorded; unconfirmed consumption is not
inferred. Page, AccessGuard, and browser cleanup are bounded best-effort.
Candidate failure metrics also carry `error_type` and `error_message`. The
entry-only runner reports missing confirmed consumption as
`AccessConsumptionUnconfirmedError` instead of a generic `LookupError`.
Adapters may override `initialize_entry_only()` when grant-only access
confirmation must not perform full crawl readiness or capture setup. Cleanup
of AccessGuard, page, and BrowserSession is bounded and never replaces an
active candidate error; interruption is preserved only when no primary error
is already in flight.

### Phase 1 runtime settings / pacing

rootの`crawler.yaml`は`runtime_settings.py`が読み込み、`SiteRuntimeSettings`へresolveする。
ファイルまたはsite entryがない場合は`page_turn_delay_ms=1000`、`inter_candidate_delay_ms=3000`を使う。
不正なdelay（負数、bool、文字列、float）は明示的に失敗し、0はoperator overrideとして有効である。
CrawlerRunnerはYAMLを読まず、CLI/Batchがresolved値を`RunConfig`またはBatch orchestrationへ渡す。

正常なCONTENT captureでは、logical page/spreadの全artifactをsaveした後にmanifest/progressを一括persistし、
`page_turn_delay_ms`を1回だけ待ってからinitial `adapter.go_next()`、`adapter.wait_for_change()`を呼ぶ。
delayはadapter timeout/grace/retry budgetの外側で、AD、loading polling、same-content wait、entry clickには適用しない。
BatchはsiteへアクセスしたcandidateのPageをcloseした後、次のsite-accessing candidateの前に
`inter_candidate_delay_ms`を1回だけ適用し、末尾candidateやCatalog local skipには適用しない。

Magapoke BatchはDiscoveryのlatest-firstを維持し、同一Work内を`published_at ASC (NULL last), source_id DESC`
で処理する。Jump+もDiscoveryのlatest-firstを維持し、同じWork内orderingを通常direct candidateへ適用する。
既存のdirect先行とWork間orderingは維持する。AccessGuard、403/429 stop、challenge/CAPTCHA、
Phase 2のAccessGuardは3site共通で接続済みで、relevant hostの403/429、明示challenge、visible
CAPTCHAをdistinct stop reasonとして扱う。Batchのbody-free access metricsは`output/metrics/*.jsonl`
へ逐次flushされ、fatal stop前のCatalog更新とmetricsを保持する。fatal access stop後は、
CONTENTのpacing後およびAD advancement前に再確認し、新しいintentional `go_next()`を開始しない。
Phase 3では、Site Policyがgeneric access resourceのsupported/order contractを提供し、
Plannerがexplicit `quota_resource`を検証する。Batchはnormal/default pass後にPolicy順でreplanし、
requested resource以外へのsilent fallbackをしない。Phase 4/5では同じcontractをgrant-onlyにも使い、
Work Ticket cooldown、Premium live balance、Policy順`all`を実装している。

### Capture dedupe semantics (current)

Capture fingerprints are artifact evidence, not global logical-page identity.
The runner now deduplicates a captured part only when all of these match:

```text
ContentIdentity
spread part count
spread part index
capture fingerprint
```

This preserves distinct logical pages that happen to have identical encoded
bytes, and preserves both parts when a spread uses the same bytes on both
sides. A repeated capture with the same logical identity, part structure, and
fingerprints remains subject to the existing `max_same_content` guard.

The change is generic Core behavior; it is not a Zeblack-specific exception.
The persisted manifest continues to record the logical identity, part metadata,
and per-artifact capture fingerprint.

### Site-native bounded Discovery（B6 Jump+ / Z4-1 Zeblack implemented）

正式仕様は `docs/BOUNDED_DISCOVERY.md`。現在のB6実装状況は次のとおり。

- Watchlistの`DiscoveryScope(from_url / through_url)` model、YAML parse、mapping / boundary存在 / non-empty string validation: **IMPLEMENTED**
- scope付きtargetのenable / disable等のWatchlist rewrite preservation: **IMPLEMENTED**
- scopeなしtargetの既存load / rewrite互換: **IMPLEMENTED**。scopeなしtargetは従来どおりunboundedとして扱い、scope専用CLI optionは追加していない
- common Discovery capability gate: **IMPLEMENTED**。`DiscoveryAdapter.supports_bounded_discovery` のdefaultは`False`で、明示的にopt-inしたAdapterだけboundedを受け付ける。Magapoke / BookWalker / Manga ONE / Jump+ / Zeblack / Piccoma / Hanayume / Younganimal / ComicFUZ / Kadocomi / Comic DAYSはopt-in済み。未対応Adapterはdefault `False`のまま
- scope付きtargetを未対応Adapterへ渡した場合: **IMPLEMENTED**。Work作成前にincompleteとして停止し、`iter_records()`、unbounded fallback、Item / Source / SourceTarget同期を行わない
- bounded full: **IMPLEMENTED**。対応Adapterがyieldしたrecordは通常どおり同期し、正常終了時は`complete=True` / `stopped_reason="exhausted"`とする。global missing-source reconciliationは実行しない。完全一覧を把握できるAdapterはscope slice前にglobal display-position hintを付与し、scope-local `1..N`へ再採番しない。hintなしbounded runはincompleteでfail closedとする
- bounded incremental common semantics: **IMPLEMENTED**。generic known-streak（5件の連続distinct known identity）と`incremental_stop_decision()`のstop hookをscopeなしと同じ順序・契約で適用する。global hintがあればそれをauthorityとして使い、boundedでhintがなければincompleteとする
- Magapoke bounded Discovery: **IMPLEMENTED**。既存strict parserで`title_id` / `episode_id`を検証し、parse済みlatest-first listing order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。invalid / foreign / different-title / missing / reversed boundaryはyield前にincompleteとする
- Magapokeのboundary validation前yield防止: **IMPLEMENTED**。既存の全listing parse・buffer構造の後にrange確定してからyieldするため、invalid scopeでCatalog partial writeを行わない
- BookWalker bounded Discovery: **IMPLEMENTED**。strict `/deUUID/` parserでproduct UUIDをboundary identityとし、full collected series-list membershipと既存のcollect order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。invalid / foreign / missing / reversed boundaryはproduct observation前にincompleteとする
- BookWalkerのfirst-volume inference: **IMPLEMENTED**。scope slice前にfull productsで候補を算出するため、bounded sliceの外側にある後続巻を文脈として維持する
- Manga ONE bounded Discovery: **IMPLEMENTED**。strict HTTPS / `manga-one.com` chapter parserで`work_id` / `chapter_id`をboundary identityとし、complete listingのglobal positionを計算してから既存のlisting order上でfrom-only / through-only / both / singletonのinclusive rangeを選択する。relative hrefはpage URLとの`urljoin()`後にparseし、foreign hostはrejectする
- Manga ONEのbounded buffering: **IMPLEMENTED**。scopeなしは既存のpage/card単位streamingとpartial-refreshを維持し、scope付きだけ全listingをbufferしてpagination完了・boundary validation後にyieldする。invalid / foreign / different-work / missing / reversed boundaryやbounded pagination failureではCatalog partial writeを行わない
- Jump+ bounded Discovery: **IMPLEMENTED**。既存のstrict episode URL parserで`episode_id`をboundary identityとし、全rangeのpagination・duplicate・network scope・total validationを完了した`records_by_id`のcanonical insertion order上でglobal positionを計算してからfrom-only / through-only / both / singletonのinclusive rangeを選択する。latest-first ordering、range direction、row directionは変更しない。invalid / foreign / missing / reversed boundaryはyield前にincompleteとする
- Jump+ bounded buffering: **IMPLEMENTED**。scope付きfull / incrementalとも全rangeをbufferしてからboundary sliceをyieldし、後続range失敗時にpartial recordをyieldしない。scopeなしincrementalの既存streamingとscopeなしfullの既存全件bufferは維持する
- Jump+ / bounded cross-site no-merge regression: **IMPLEMENTED**。bounded対応Fakeを使った共通回帰で、同じ`work_key`でもsiteをまたぐItem自動mergeを行わないことを確認している
- Zeblack production Adapter bounded support: **IMPLEMENTED**。strict chapter-list / viewer parser、DOM/protobuf exact-set validation、latest-first canonical order、raw DOM oldest-first index由来のglobal position、chapter_id boundary slice、およびyield前bufferingを`ZeblackDiscoveryAdapter`で実装済み。Z4-1時点ではDiscovery registryのみ登録し、Z5でBatch Policy registryにも登録した
- Piccoma bounded Discovery: **IMPLEMENTED**. Strictly parses canonical viewer URL product/episode identity, buffers and validates the complete product listing, then selects an inclusive latest-first range. Assigns whole-work `display_position` from oldest-first native DOM index + 1 before slicing. Free classification requires exactly the `PCM-epList_status_free` marker set across wrapper and descendants plus exact `¥0`. Fresh viewer preflight, horizontal viewer/capture, and the available+free-only direct Site Policy with local Batch integration are implemented. Phase 06-D code review and independent live Tester passed with BLOCKING 0: the standard two-product Batch-to-ZIP route produced 24 and 15 validated lossless WebP pages, explicit END, and completed Catalog artifacts. WebP requires exact JPEG-to-canvas provenance, verified white compositing, VP8L validation, and an exact RGB round-trip; encoding/provenance fallbacks remain PNG. Other layouts/resources and unobserved draw/backdrop variants remain unsupported.
- Hanayume / Younganimal / ComicFUZ bounded Discovery and listing proof: **IMPLEMENTED**。各Adapterは検証済みfull listingと既存global positionを使い、slice前にinventoryを保持する。Younganimalのaccount-only rowsはpublic inventoryやpositionに追加しない。Fullの正常exhaustion後のみ証拠を公開し、access semanticsを変えない
- Comic DAYS bounded Discovery and listing proof: **IMPLEMENTED**。検証済みAtom/readable-product series listingからnative series identityとlatest-first positionsを確定し、canonical episode boundaryを同一listing内で検証してからinclusive sliceを返す。Full proofは正常exhaustion後のみ公開する
- Kadocomi opt-in bounded Discovery and listing proof: **IMPLEMENTED**。`discovery_scope`または`archive_order`指定時のみ、work-bound native arrays、explicit `episodeNo`、UUID/type/active data、exact reverse orderをstrictに検証する。legacy unconfigured pathはpublic rowsのみでposition inferenceを行わない。番号gapはSourcesとして捏造せず、existing Catalog Source absent from proofは過去positionを保持したまま`missing_listing`としてscope syncをblockする
- Listing inventory evidence is committed only after successful Full exhaustion and Catalog finalization. Incremental, failed, partial, or early-closed runs cannot publish proof. Position writes affect observed inventory identities only; absent Catalog Sources retain historical positions, but those are not current-listing evidence and do not unblock reconciliation.
- 未対応Adapterでは `supports_bounded_discovery=False` を維持する。scope付きtargetはunbounded fallbackせずWork / Item / Source同期前にfail closed

The following historical summary predates Z4-1; the current production
bounded adapters include both Jump+ and Zeblack. Site Policy and Batch
changes remain outside the Zeblack Discovery phase.

### Archive health check and recrawl preparation (implemented)

`scripts/prepare_recrawl.py` inspects only `completed` Catalog Items in an
exact `--site` and/or Work title scope. It does not run Discovery or modify
sources, source targets, crawl runs, or ZIP contents. The current site policy
mapping is intentionally limited to the confirmed production capture paths:
Comic DAYS and Magapoke prefer JPEG (`.jpg`/`.jpeg`) with PNG fallback, while
MANGA ONE, Hanayume, and Younganimal prefer source-native WebP with PNG fallback. Hanayume's
mapping was added on 2026-10-18 for the observed resized Yona PNG archives; Younganimal's
mapping was added on 2026-10-19 after the fractional-destination capture correction.
BookWalker is supported as of 2026-10-22 with JPEG preferred and PNG fallback.
A cover-only `page-0001.png` is `PREFERRED_ONLY` when the archive also contains
at least one JPEG companion; all other PNGs remain recrawl candidates. This is
an extension-based recrawl policy, not proof that every PNG has reduced
fidelity: a verified native-size PNG retained after codec failure is also
classified as a fallback format.
An explicitly unknown
site fails closed; work-only scans skip sources whose policy is undefined.

ZIP page members are inspected at archive root with case-insensitive
extensions. `PREFERRED_ONLY`, `FALLBACK_INCLUDED`, `UNEXPECTED_FORMAT`,
`BROKEN`, `MISSING`, and `AMBIGUOUS_ARTIFACT` are reported using site-neutral
classifications. Default output lists only problems; `--show-all` also lists
preferred items. `--ignore-missing` keeps MISSING in the classification
summary but excludes it from problems, recrawl candidates, and apply changes;
with `--show-all` it is printed as `MISSING (ignored)`.

The default is dry-run. With `--apply`, fallback/unexpected/broken archives
are moved to `output/reimport-backup/<timestamp>/` while preserving their
relative path under `output/Books` where possible, then their Catalog locator
is updated and the Item is returned to `pending`. Missing artifacts retain
their locator, are marked `missing`, and then return to `pending`. Ambiguous
artifacts and ignored missing artifacts are never mutated. Move, artifact, and
pending failures are reported as partial failures without a rollback
framework. Synthetic ZIP coverage is in
`tests/unit/test_prepare_recrawl.py`; no real Catalog `--apply` run is part of
the implementation verification.

`prepare_recrawl.py --apply` deliberately leaves the old completion-status JSON
in place after moving a ZIP and returning its Item to `pending`. A subsequent
normal Batch may reuse that sidecar only when the candidate ZIP is absent and
the status plus Catalog run/Artifact history proves the same Source, as described
in the archive-output preflight above. This does not clear or rewrite the sidecar
before the crawl: a crawl or pre-package failure leaves it byte-for-byte intact;
successful packaging writes the refreshed status. If hashing or Catalog finalization
fails after packaging generated the new ZIP/status pair, that pair remains for
inspection; the prior sidecar is not restored over it. A foreign, malformed, or
unprovable status remains a hard stop for operator review.

BookWalker usage: `python scripts/prepare_recrawl.py --site bookwalker --catalog
catalog.sqlite --show-all` performs a read-only scan. Exactly one root member
named `page-0001.png` (case-insensitive) is an allowed fallback only when at
least one JPEG member exists and no JPEG has the `page-0001` stem. No additional
PNG is permitted by this exception; unexpected formats remain problematic.
An accepted cover PNG plus JPEG body is `PREFERRED_ONLY`, with
`allowed_fallback_count=1` and `fallback_count=0`, and is excluded from apply.
Body PNGs, PNG-only archives, nonstandard PNG naming and duplicate first-page
PNG/JPEG remain recrawl candidates. ZIP entry order is not reading order and
does not affect the rule. `ArchiveInspection.allowed_fallback_count` is appended
after the pre-existing fields, preserving positional constructor compatibility;
printed inspection details include `allowed_fallback`.

This is an archive-name/extension policy, not proof that page 1 is actually a
cover, that PNG is lossy, or that a source JPEG exists. Verified source-native
PNG remains valid capture output. Capture/DRM/provenance logic is unchanged,
and a later crawl is not guaranteed to produce JPEG. Only completed Catalog
Items with recorded successful ZIP Artifacts are inspected; orphan archives
are outside scope. `--apply` explicitly uses the existing backup/Artifact/
pending workflow and preserves source grants and historical runs. Batch access
policy still decides whether a pending item is readable. Details and examples:
`docs/BOOKWALKER_RECRAWL.md` and `note/01_bookwalker.md`.
Validation for this integration: all 43 preparation-script Unit cases passed
(0 failed/skipped; one existing pytest-asyncio deprecation warning), including
all existing site policies and synthetic apply. Ruff (`scripts/prepare_recrawl.py
src tests`) and diff checks passed. No browser Integration, Research/Probe,
real Catalog apply, live recrawl or full repository suite was run because only
the archive-policy script and its documentation changed.

Hanayume usage: `python scripts/prepare_recrawl.py --site hanayume --work "暁のヨナ"
--catalog catalog.sqlite --ignore-missing` is read-only; adding `--apply` moves the selected
old archives and returns their Items to pending without clearing source grants or work cooldowns.
The work title must match exactly, and `--site` prevents the same Work's Piccoma Sources
from entering this scan. The 2026-10-18 real dry-run found 20 FALLBACK_INCLUDED candidates,
no missing/broken/ambiguous artifacts, and made no Catalog/file changes. The policy/classifier
and backup/apply tests passed 24 cases (0 skipped); synthetic apply verifies that moved ZIP
bytes are preserved. `batch run --site hanayume` has no `--work` filter and may consider
pending Items across all managed Hanayume works. Watchlist `enabled` controls Discovery
execution only; Batch ownership uses the independent `discovery_scope` →
`sources.acquisition_enabled` flags reflected by Discovery or optional maintenance. A Source assigned out of scope is retained but skipped
before Site Policy evaluation.

Younganimal usage: `python scripts/prepare_recrawl.py --site younganimal --catalog
catalog.sqlite --ignore-missing` scans all completed Younganimal Items; add an exact
`--work "ホーリーランド"` to limit preparation to that title. The 2026-10-19 real dry-run
scanned eight completed Items: six PREFERRED_ONLY and two FALLBACK_INCLUDED (Item 25335,
six PNGs from `スピカ～羽海野チカ初期短編集～`; Item 33083, ten PNGs from `ホーリーランド`).
Unexpected, broken, missing, and ambiguous counts were zero. Report:
`output/younganimal-recrawl-dry-run-20261019.txt`. No real `--apply` or re-crawl was performed.

Adding `--apply` uses the same backup/Artifact-locator/pending path and retains source grants,
quota state, and historical runs. Normal Batch still considers site-wide pending Items, including
unrelated pending Younganimal Items. The policy classifies PNG format, including native-size
codec-fallback PNGs; it does not assert that every PNG is resized or that every later crawl will
produce WebP. All 29 preparation tests passed (0 failed/skipped; one existing pytest-asyncio
deprecation warning), including Younganimal upper-case/mixed extensions and synthetic apply
with exact ZIP-byte, source, and historical-run preservation. Ruff (`scripts/prepare_recrawl.py
src tests`) and changed-file diff checks passed. Browser Integration, Research/Probe, live
re-crawl/apply, and the full repository suite were not rerun for this static site-policy addition.

Hanayume Source identity maintenance is a common Catalog v7 transaction with
an explicit Hanayume-only operator entry point. It preserves the retained
Item/Source graph and historical CrawlRun snapshots, rejects non-pristine
donors, invalidates listing proof, and never changes ZIP paths. No schema
version or alias table is added; the old external ID remains in each historical
snapshot. The required dry-run token and apply procedure are in
`docs/HANAYUME_SOURCE_IDENTITY.md`.
Isolated copy validation also covered the proven `ng-life` replacement from
`ca6472995ecea:90fac353b1178` to `ca6472995ecea:5fa301a1e55e3`: Full listing
recovered Scope Sync, retained the completed Item/Source and all run, artifact,
and quota rows, and performed zero ZIP operations. The separate CLI copy
verified dry-run byte stability and transactional apply; the operational
Catalog and ZIPs were not used.
The affected Discovery/Catalog/Batch/Scope/Archive suite passed 477 tests with
no failures or skips, and the existing Hanayume browser enumeration suite
passed 15 tests with no skips. An isolated Batch plan left the retained
completed Source unscheduled, preserved archive stem `001-NGライフ-scene1`,
and performed zero ZIP operations.
The final repository run collected 5,508 tests: 5,506 passed, 2 failed, and
0 skipped. One Piccoma frame-geometry failure passed on an isolated rerun; the
other is the pre-existing runtime-settings expectation that assumes
bookwalker200 while the user `crawler.yaml` has 0, and the tracked config
injection check passes. This is not an all-green exact-head run. Independent
review approved the identity change, and the final operational compare found
schema v7 and both original Source/Item graphs unchanged.

B1/B2/B3/B4/B5/B6ではtitle、order、episode number、漢数字変換、cross-site fuzzy matchをscope判定に使わない。Catalog schema、Batch Planner / Executor、CrawlerRunner、BookWalker、Magapoke、Manga ONE以外ではJump+だけproduction bounded Discoveryを実装している。bounded scope内recordは通常のItem / Sourceとして同期するが、cross-site Itemのautomatic mergeやcompleted伝播は行わず、重複crawlは安全側の挙動として許容する。

将来cross-site dedupeが必要になった場合はphysical Item mergeより先にhuman approval付きnon-destructive equivalence mappingを検討する。physical mergeは現計画の対象外である。
### GUI live monitor Phase 01 (2026-10-25)

The management GUI worker is launched with Python ``-u`` and
``PYTHONUNBUFFERED=1``. This applies only to the child worker; controller
start gates, identity checks, cancellation, and log sink failure handling are
unchanged. Separate ``stdout.log`` and ``stderr.log`` files remain sanitized
and flushed by the controller.

``management.log_tail.LogTailReader`` is Qt-free and reads only the fixed
``stdout.log``/``stderr.log`` names under ``JobStore.job_dir(job_id)``. It
keeps independent byte offsets and incremental UTF-8 decoders, bounds initial
history and each read, and safely reinitializes after a missing or truncated
file. It does not open paths supplied by event payloads or merge the streams.

GUI Discover emits a ``discovery_result`` event containing observed, new,
known, complete, stopped_reason, and warnings facts from the returned
``DiscoveryResult`` and prints the same fields as the CUI. A target exception
emits keyed ``candidate_finished`` with ``result=failed`` before the existing
fail-stop propagation. Missing result numbers remain unknown rather than
being fabricated as zero.
Phase 01 review correction: LogTailReader file identity uses device/inode and
immutable creation time where available; POSIX metadata-change time is not
used, so ordinary append does not replay a stream. Missing or recreated files
reset offsets and decoder state, including same-size replacements. Initial
tail omission is exposed per stream through ``metadata(stream)``. UTF-8 tail
boundary skipping is limited to the maximum three continuation bytes in one
code point.
## GUI live monitor (current implementation, 2026-10-25)

The MainWindow keeps the existing path row, toolbar, horizontal tree/detail
splitter, action row, and error label. A vertical splitter adds a lower
ExecutionMonitor; its body can be collapsed while its heading remains visible.
The existing upper content is wrapped in a QScrollArea viewport, preserving
the form/table minimums while allowing the user to enlarge the monitor. At
1400x850 the real splitter handle can reserve at least 400px for the monitor;
resize, polling, and follow do not reset the chosen ratio, and collapse/expand
restores the previous expanded size. The first snapshot fully collapses the
inventory tree; later reloads preserve the user's manual expansion state. The
vertical splitter adds both children before configuring `setCollapsible`, so the
startup out-of-range warning is not emitted. Root's final synthetic native helper
confirmed Windows/DPR 1.5, actual 980x600, a 230px monitor, a 326px upper
viewport, bounded headers, collapsed tree, Japanese log text, and no warning.
The independent follow-up review is approved with BLOCKING 0. The monitor and
JobsPage are passive observers of the single JobController and
JobStore. View refresh or initialization failures are isolated from queue,
start, stop, force-stop, reconcile, and safety state handling.

LogTailReader is Qt-free and opens only the fixed stdout.log/stderr.log files
under the selected JobStore job directory. Each stream has bounded incremental
reads, UTF-8 decoder/file-identity reset, omission metadata, and independent
view/cache state. QPlainTextEdit appends use an independent QTextCursor so a
manual selection or viewport anchor is retained. Raw streams remain separate;
cross-stream wall-clock order is explicitly unavailable.

JobResultPresenter is an immutable Qt-free DTO boundary. Controller/DB state
remains authoritative; Events and metrics add observed facts only. Events use
bounded keyset/latest reads, preserving current task/site context and selected
Discover facts after raw history trimming. Authorized metrics JSONL is read
incrementally with partial-line, truncation, scope, malformed-input, and
redaction handling. Batch summaries are the primary evidence, and missing or
partial metrics stay unknown. Discover keeps per-site/key success, failure,
disabled, unstarted, and unknown states. Grant results deduplicate by strong
site/work/resource identity, retain tri-state consumption, and never treat
consumed OK as post-processing success without aligned candidate evidence.

Summary and problem panes are bounded, scrollable, copyable, and explicitly
mark omitted content. Jobs history keeps list/detail selection and viewport
independent from the monitor and uses latest-event SQL, so terminal context
remains available beyond the old first-500 window. Child execution subprocesses
use UTF-8 only at the child boundary; parent CLI encoding is unchanged.

Phase 04 verification is synthetic/offscreen and native Windows capture only.
Earlier native captures record the pre-follow-up 980x600 request as actual
980x628. The follow-up geometry tests validate a scrollable 980x600 viewport,
plus 1400x850 and additional high-DPI
logical sizes with host DPR 1.5; worker/browser startup is disabled. The durable
checks cover 50,000 Events, 50,000 log lines over 5 MiB, timer responsiveness,
bounded rendering, manual anchor/follow, history, rerun, and input-hash
preservation. No real site or CDP was accessed, and no operational Catalog,
Watchlist, Books, quota, or ticket input was used; all fixtures were synthetic.
## BookWalker PNG recrawl and durable diagnostics (2026-10-30)

BookWalker archive inspection treats a cover-only `page-0001.png` as
`PREFERRED_ONLY` when the same archive has at least one JPEG companion; the
cover may then be selected for recrawl, but this is not a body or terminal
exception. All other PNGs, including PNG-only covers and terminal-looking
images, remain `FALLBACK_INCLUDED`. The adapter may classify a positively
identified terminal notice/logo as an AD screen during normal navigation, but
this state decision does not alter ZIP or Catalog recrawl policy. Unknown
terminal images remain content.

BookWalker capture attempts write bounded, sanitized, site-local JSONL under
`output/diagnostics/bookwalker/` (or `BOOKWALKER_DIAGNOSTICS_DIR`). Records keep
the run UUID, page counter, capture stage/reason, candidate count and selected
draw/geometry metadata without URLs, credentials, signed query values, or image
bytes. Diagnostic write failures never change capture output. This is an
adapter-local diagnostic sidecar; Core capture and packaging contracts are
unchanged.


## BookWalker capture diagnostics contract (2026-10-30)

The terminal AD gate first inspects the complete pinned visible canvas with the
calibrated source-independent descriptor. It requires the authorized content
identity, counter, actual canvas identity, and stable frame before and after the
read; a trace ID is optional. Notice is recognized only at N-1/N and logo only
at N/N, using the registered role descriptors. If the complete-canvas read is
unavailable or does not match, the ordinary exact native artifact path remains
the fallback. Screen dimensions, filenames, timing, and source/JPEG similarity
are never attribution evidence. Unknown or unstable artifacts remain content,
and existing END/final-navigation checks remain authoritative.
