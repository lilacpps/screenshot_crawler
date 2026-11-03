# BookWalker legacy PNG re-crawl

Use the existing `scripts/prepare_recrawl.py` Catalog-driven scanner. BookWalker
prefers JPEG (`.jpg` / `.jpeg`), with a PNG exception only for the last five
saved pages **when at least one JPEG page is present**. PNGs in the first ten
saved pages are fallback candidates unless they also fall within that tail.
This exception does not convert PNGs or modify the BookWalker
adapter's source-preserving fallback behavior.

- JPEG-only archives and archives whose PNGs occur only in the last five
  saved pages are `PREFERRED_ONLY` and excluded by default. Explicit Item IDs
  with `--force` can prepare them when a visual defect requires another capture.
- Other body PNGs, PNG-only archives, and unsupported image formats are flagged.
- The scanner checks ZIP CRC and ignores known operating-system metadata.

Run in the repository root (PowerShell):

```powershell
# Read-only inspection, including accepted tail PNGs
python scripts/prepare_recrawl.py --site bookwalker --catalog catalog.sqlite --show-all

# Optional: prepare only problematic completed Catalog items for re-crawl
# Review the dry-run above first. Original ZIPs are moved to backup, not deleted.
python scripts/prepare_recrawl.py --site bookwalker --catalog catalog.sqlite `
  --library-dir output/Books --backup-root output/reimport-backup `
  --ignore-missing --apply

# Confirm the pending candidates/access policies before crawling.
python -m screenshot_crawler.cli batch plan --site bookwalker --catalog catalog.sqlite

# Re-crawl eligible items using the existing batch workflow.
python -m screenshot_crawler.cli batch run --site bookwalker `
  --catalog catalog.sqlite --output-root output/batch `
  --library-dir output/Books --limit 1
```

To select individual Catalog Items, repeat `--item-id`. IDs are Catalog Item
IDs, not the numeric ZIP filename prefix. Site/work filters intersect the ID
selection; without those filters, Item IDs alone are sufficient scope. Unknown,
non-completed or out-of-scope requested IDs reject the whole operation before
any archive moves. Duplicate IDs are processed once. Other Items are not scanned.

In the previously inspected Catalog, ZIP prefix 013 mapped to Item 1880 and
prefix 019 to Item 1874. To include an otherwise `PREFERRED_ONLY` archive for
a visual defect, use explicit Item IDs with `--force`:

```powershell
# Read-only: verify the two selected archives
python scripts/prepare_recrawl.py --site bookwalker --work "ようこそ実力至上主義の教室へ" `
  --item-id 1880 --item-id 1874 --force

# Prepare those two Items only; backup their ZIPs and return them to pending
python scripts/prepare_recrawl.py --site bookwalker --work "ようこそ実力至上主義の教室へ" `
  --item-id 1880 --item-id 1874 --force --apply
```

`--force` requires explicit `--item-id` selection and only includes otherwise
`PREFERRED_ONLY` archives. It does not change format classification, bypass
ambiguous-artifact safeguards, override `--ignore-missing`, or start a crawl.
Without `--force`, IDs simply narrow the usual format-based candidates.

**Limitations:** The scanner only inspects completed Items with recorded successful
ZIP Artifacts in Catalog. It does **not** discover orphan ZIPs imported before
Catalog tracking and never invokes Discovery. Those archives need separate
Catalog reconciliation or a filesystem-based inventory. A resulting pending
Item is not guaranteed to be currently readable: the existing BookWalker
access policy still governs owned/quota availability.

The tail exception uses the five highest saved-page numbers
across all JPEG/PNG members, not ZIP entry order, the last five PNGs, or the
viewer's original page counter. All JPEG/PNG members must have unambiguous
standard names (`page-0001`, `page-0002`, ..., `page-10000`, etc.) for this
exception; filename case is ignored. Old/nonstandard names and duplicate page
numbers do not receive the exception. There is no separate cover or first-ten
exception. In short archives, an opening page can still be one of the last five
saved pages and receive the tail exception.
An allowed PNG is counted in
`allowed_fallback`, rather than `fallback`, even if another body PNG still
requires re-crawl.

This is a user-accepted position/format policy, not a claim that the final five
images are terminal notices, that PNG is lower quality, or that JPEG recovery
is possible. No terminal-image recognition or live site access is required.
