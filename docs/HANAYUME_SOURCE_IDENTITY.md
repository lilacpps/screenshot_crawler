# Hanayume episode identity maintenance

Hanayume may publish the same episode under a new episode ID while the old
episode document remains reachable. Discovery does not merge a missing Source
with a new listing row from title, display position, or neighboring rows.

The supported operator path is a read-only plan followed by an explicit apply.
Use a backup and an isolated copy, then run a complete Full Discovery and
Scope Sync preview/apply on that same copy before considering an operational
Catalog update. No Catalog migration or schema change is required.

```powershell
python -m screenshot_crawler.cli catalog backup --catalog .\catalog.sqlite --output .\catalog-copy.sqlite
Copy-Item .\watchlist.yaml .\watchlist-copy.yaml
python -m screenshot_crawler.cli catalog source-identity --catalog .\catalog-copy.sqlite --site hanayume --work-key ng-life --old-external-id ca6472995ecea:90fac353b1178 --new-external-id ca6472995ecea:5fa301a1e55e3 --new-url https://hanayume.com/episodes/5fa301a1e55e3 --reason "site API identity proof" --dry-run --json
python -m screenshot_crawler.cli catalog source-identity --catalog .\catalog-copy.sqlite --site hanayume --work-key ng-life --old-external-id ca6472995ecea:90fac353b1178 --new-external-id ca6472995ecea:5fa301a1e55e3 --new-url https://hanayume.com/episodes/5fa301a1e55e3 --reason "site API identity proof" --apply --plan-token <TOKEN>
python -m screenshot_crawler.cli discover --key ng-life --mode full --watchlist .\watchlist-copy.yaml --catalog .\catalog-copy.sqlite
python -m screenshot_crawler.cli watch scope-sync --work-key ng-life --watchlist .\watchlist-copy.yaml --catalog .\catalog-copy.sqlite --dry-run --json
python -m screenshot_crawler.cli watch scope-sync --work-key ng-life --watchlist .\watchlist-copy.yaml --catalog .\catalog-copy.sqlite --apply --json
```

The dry-run prints a plan token. Review the donor state and byte-level copy
before applying; replace `<TOKEN>` with the token from that exact dry-run.
Apply takes the Catalog job lock, rechecks the token in the same transaction,
and rolls back all changes on any error. Keep the original Catalog and ZIP
library untouched until the copy has passed Full Discovery and Scope Sync
review.

After the copy passes review, create a fresh operational backup with
`python -m screenshot_crawler.cli catalog backup --catalog .\catalog.sqlite --output .\catalog-before-apply.sqlite`.
Repeat the dry-run against the current operational Catalog to obtain a fresh
token, then apply that token to the same Catalog and run Full Discovery
followed by Scope Sync preview/apply. Do not replace the operational database
wholesale with the verified copy; concurrent Catalog changes must be detected
by the fresh plan token.

The retained old Item and Source IDs keep their status, CrawlRuns, Artifacts,
quota state, and archive locator. The current Source external ID and web
target locator are updated. A pristine Source created by an earlier Discovery
 may be removed only when its Item is pending with no manual title or note,
CrawlRuns, Artifacts, quota grant, or sibling Sources and its targets are the
normal web/default shape. Any donor history or conflict rejects the operation;
the operator must prepare a separate migration.

The applied transaction retains the old ID in historical
`crawl_runs.external_id_snapshot` values; those snapshots are never rewritten.
The operator reason and body-revision possibility are included in the
dry-run/apply diagnostics. Discovery
inventory evidence is invalidated and acquisition scope sync becomes stale;
the next successful Full Discovery rebuilds the proof. ZIP files are never
renamed, removed, or overwritten by this operation.

Copy-only verification completed against the `ng-life` Catalog and an isolated
watchlist: the exhausted Full run proved
`ca6472995ecea:90fac353b1178` → `ca6472995ecea:5fa301a1e55e3`, retained the
completed Item/Source and all CrawlRun, Artifact, and quota rows, removed the
history-free donor, and rebuilt Scope Sync from stale to synced. A separate
CLI dry-run/apply copy verified the same retention and token checks. Both
checks reported schema v7, no ZIP operations, and no writes to the operational
Catalog. The API proof establishes identity fields only; it does not establish
body equality. A separate read-only Batch plan kept the retained completed
Source unscheduled and preserved archive stem `001-NGライフ-scene1`.

The observed native proof was HTTP 200 with no redirect for both exact API
URLs. The old endpoint for episode `90fac353b1178` returned
`episode.id=5fa301a1e55e3`, `series.id=ca6472995ecea`, and
`episode.indexId=summary.indexId=609597`, with matching
`summary.id`/`access.episodeId`; an independent GET of the new endpoint
returned the same identity tuple. This proves the site identity replacement,
not equality of the episode body.
