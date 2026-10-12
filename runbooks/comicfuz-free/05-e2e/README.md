# Phase 05 — Independent Live E2E and Final Gate

**Initial status: NOT STARTED.** [Main contract](../README.md) / [evidence ledger](../PROGRESS.md).

## Standard CLI path with isolated files

Use the existing shared Crawler Chrome/CDP with exactly one live browser operator. Create a NEW temporary Watchlist, Catalog and output root (e.g. `output/comicfuz_experiment/`), never default Catalog or production output. Confirm the current `--help` syntax and available free targets before running commands. The following PowerShell commands are examples after site registration, not evidence that the adapter exists already:

```powershell
$env:PYTHONIOENCODING = "utf-8"
New-Item -ItemType Directory -Force output\comicfuz_experiment | Out-Null
python -m screenshot_crawler.cli watch add --watchlist output\comicfuz_experiment\watchlist.yaml --key comicfuz-sample --work-key comicfuz-work-1970 --site comicfuz --url "https://comic-fuz.com/manga/1970?position=thumbnail" --label "ComicFUZ sample"
python -m screenshot_crawler.cli discover --key comicfuz-sample --mode full --watchlist output\comicfuz_experiment\watchlist.yaml --catalog output\comicfuz_experiment\catalog.sqlite
python -m screenshot_crawler.cli discover --key comicfuz-sample --mode incremental --watchlist output\comicfuz_experiment\watchlist.yaml --catalog output\comicfuz_experiment\catalog.sqlite
python -m screenshot_crawler.cli batch plan --site comicfuz --catalog output\comicfuz_experiment\catalog.sqlite
python -m screenshot_crawler.cli batch run --site comicfuz --catalog output\comicfuz_experiment\catalog.sqlite --output-root output\comicfuz_experiment\batch --library-dir output\comicfuz_experiment\library --limit 1
```

The work seed is **not promised to contain eligible public-free episodes**. If plan is empty, do not force a charge/ticket chapter into eligibility: find another genuinely public-free work and repeat in a fresh isolated Catalog. After the first passed run, test a second free episode/layout if currently available; otherwise document the coverage shortfall. No live paid/quota negative testing that could spend entitlements.

## Independent Tester audit

1. Confirm the observed anonymous work/episode identity, the publicly enumerable list/count, real oldest→newest global position and free classification. Distinguish truncated anonymous history from complete full coverage. Compare full vs incremental and bounded if implemented; verify re-Discovery does not change a completed artifact.
2. Confirm `batch plan` contains only positive `free` and all other modes are skipped. Run local/synthetic denied/collision/stale-free cases; live trial must neither log in nor use charge/ticket/medals.
3. For each captured target, independently check whole page sequence, actual last-body→END transition, original/source attribution versus displayed contents, first/middle/last appearance, all member dimensions, rendering pixel proof as applicable, RTL spread reading order, no UI/promotions or other chapter images, and zero unexpected duplication/missing body pages. Inspect all pages programmatically for members/count/order/CRC and sample visually; source-pixel equality must be validated to the level claimed.
4. Compare normal CLI Manifest to ZIP member list, filenames/global prefix, CRC, SHA/hash where available, count, image decode, site/native source identity, Catalog artifact and `completed` status. A failed run retains pending and has no false success artifact.
5. Review AccessGuard/pacing/retry/timeouts, secret-free logs, no entitlement action and scoped outputs. Reviewer checks actual diff plus evidence; Tester writes only isolated audits/logs. Run relevant neighboring adapter regression when shared code changes.

## Exit / reporting

- **PASS** only if normal isolated Discovery→Batch→Crawl→END→ZIP→Completed succeeds on at least one currently anonymous/public-free episode; complete data integrity and independent reviewer BLOCKING 0.
- If browser/site/content/public-free target is unavailable, distinguish **local tests PASS**, **live NOT VERIFIED/BLOCKED**, and **overall NOT DONE**. Do not invent page counts, source format or successful E2E.
- Record branch/head SHA; modified paths; source formats and identity proof; full/incremental counts and position; ZIP/member/hash audit; all targeted/affected tests, skips and omitted test categories; Reviewer/Tester results and any unresolved limitations in `PROGRESS.md`, site README and `note/13_comicfuz.md`. Do not merge `main` automatically.
- **The future charge/ticket/medal phase is not required to exit free-only v1.**
