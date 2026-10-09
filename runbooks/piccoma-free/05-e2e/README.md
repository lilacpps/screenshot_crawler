# 05 — Independent E2E and final gate

Status: PLANNED. Entry: all production phases reviewed.
Tester (when available) validates separately; Lead owns sign-off.
Tester may write only its isolated test data/logs, not production files.

## Live E2E
1. In shared Crawler Chrome/CDP, execute full Discovery on product 28600
   and 28606 using an isolated Watchlist and SQLite Catalog. Compare actual
   native total/ID/order and access state; run incremental again.
2. Inspect batch plan: only proven unconditional free sources qualify.
   Include a synthetic local paid/unknown/expired/stale-free negative test,
   never a live ticket-consumption test.
3. For one **currently ¥0** item per product (where available), exercise the
   normal Discovery → Catalog → Batch → Crawl → manifest/ZIP path, not a
   PoC-only shortcut. If any supplied viewer seed is no longer free, select
   another observed free candidate, not a quota candidate.
4. Independently inspect all page identities/count and first/middle/last
   capture fidelity, multi-page spread order, dimensions/native file format,
   actual last body/END, ZIP members, manifest, no duplicates, completed status.
5. Confirm no ticket/pay/charge mutation in trace, and bounded processing
   with AccessGuard/pacing intact. Regress relevant existing adapters when
   shared boundaries changed. Do not put comic page image data or tokens
   in Git.

## Suggested commands (confirm local --help)

~~~powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_crawler_chrome.ps1
python -m screenshot_crawler.cli discover --site piccoma --mode full --watchlist output\piccoma_experiment\watchlist.yaml --catalog output\piccoma_experiment\catalog.sqlite
python -m screenshot_crawler.cli batch plan --site piccoma --catalog output\piccoma_experiment\catalog.sqlite
python -m screenshot_crawler.cli batch run --site piccoma --limit 1 --catalog output\piccoma_experiment\catalog.sqlite --output-root output\piccoma_experiment\crawls --library-dir output\piccoma_experiment\library
~~~

## Completion
Report passing/failed/skipped tests, evidence/limitations, access classification
safety, live artifact checks, git diff/commit and reviewer findings. Reopen
implementer and Reviewer for any BLOCKING. If Chrome, account/geography,
public ¥0 or compatible viewer is unavailable, mark the specific live gate
NOT VERIFIED, rather than manufacturing success. Do not auto-merge main.
