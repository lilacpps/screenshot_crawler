# BookWalker legacy PNG re-crawl

Use the existing `scripts/prepare_recrawl.py` Catalog-driven scanner. BookWalker
prefers JPEG (`.jpg` / `.jpeg`), with an explicit exception for exactly one
`page-0001.png` cover **when at least one other JPEG page is present**. The
exception does not convert the PNG, and it does not modify the BookWalker
adapter's source-preserving fallback behavior.

- JPEG-only and cover-PNG + JPEG-body archives are `PREFERRED_ONLY`.
- PNG in the body, PNG-only archives, and unsupported image formats are flagged.
- The scanner checks ZIP CRC and ignores known operating-system metadata.

Run in the repository root (PowerShell):

```powershell
# Read-only inspection, including accepted cover PNGs
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

**Limitations:** The scanner only inspects completed Items with recorded successful
ZIP Artifacts in Catalog. It does **not** discover orphan ZIPs imported before
Catalog tracking and never invokes Discovery. Those archives need separate
Catalog reconciliation or a filesystem-based inventory. A resulting pending
Item is not guaranteed to be currently readable: the existing BookWalker
access policy still governs owned/quota availability.

The cover exception is intentionally strict: `page-0001.png` must be the
only PNG. Because capture output names use actual saved-page sequence numbers
(`page-0001`, `page-0002`, ...), ZIP member order does not affect the rule.
Old archives without that naming convention are not exempted automatically.
