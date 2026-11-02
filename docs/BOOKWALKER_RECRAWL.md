# BookWalker legacy PNG re-crawl

Use the existing `scripts/prepare_recrawl.py` Catalog-driven scanner. BookWalker
prefers JPEG (`.jpg` / `.jpeg`), with explicit PNG exceptions for the
first ten saved-page numbers (`page-0001` through `page-0010`) and the last five saved pages **when at least one JPEG
page is present**. These exceptions do not convert PNGs or modify the BookWalker
adapter's source-preserving fallback behavior.

- JPEG-only archives and archives whose PNGs occur only in the first ten/last five
  saved pages are `PREFERRED_ONLY` and excluded by default. Explicit Item IDs
  with `--force` can prepare them when a visual defect requires another capture.
- Other body PNGs, PNG-only archives, and unsupported image formats are flagged.
- The scanner checks ZIP CRC and ignores known operating-system metadata.

Run in the repository root (PowerShell):

```powershell
# Read-only inspection, including accepted head/tail PNGs
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

For the observed cover defects, ZIP prefix 013 maps to Item 1880 and prefix 019
maps to Item 1874. Both currently pass the format policy, so use `--force`:

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

The head exception uses saved-page numbers 1 through 10, not the first ten PNGs
or the viewer's original counter. The tail exception uses the five highest saved-page numbers
across all JPEG/PNG members, not ZIP entry order, the last five PNGs, or the
viewer's original page counter. All JPEG/PNG members must have unambiguous
standard names (`page-0001`, `page-0002`, ..., `page-10000`, etc.) for these ranges
exception; filename case is ignored. Old/nonstandard names and duplicate page
numbers do not receive these range exceptions. The existing standalone cover
exception remains: a unique `page-0001.png` is accepted even when other members
use old names, provided there is a JPEG companion and no duplicate page-0001 stem.
An allowed PNG is counted in
`allowed_fallback`, rather than `fallback`, even if another body PNG still
requires re-crawl. Head and tail may overlap without being counted twice.

This is a user-accepted position/format policy, not a claim that the final five
images are terminal notices, that PNG is lower quality, or that JPEG recovery
is possible. No terminal-image recognition or live site access is required.

The 2026-11-02 read-only inspection of the 11 Youjitsu ZIPs found all PNGs in
the first nine or last five saved pages. The accepted first-ten range removes
the eight format-based recrawl candidates in that folder; it does not validate
visual cover quality or modify any ZIP/Catalog data. Explicit `--force` remains
available for visual defects.
