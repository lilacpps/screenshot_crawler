"""Opt-in hook loader for instrumenting the real Piccoma CLI in Phase 07.

The hook is inert unless PICCOMA_PHASE07_PROFILE=1 is explicitly set. Keep
this directory first on PYTHONPATH, followed by the research directory and the
selected source tree, so normal CLI entry points receive the same local-only
profiling hooks as the older direct Runner probe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if os.environ.get("PICCOMA_PHASE07_PROFILE") == "1":
    research_root = Path(__file__).resolve().parents[1]
    if str(research_root) not in sys.path:
        sys.path.insert(0, str(research_root))
    import profile_sitecustomize  # noqa: F401

    audit_path = os.environ.get("PICCOMA_PHASE07_MANIFEST_AUDIT_PATH")
    if audit_path:
        from phase07_manifest_audit import install_runner_manifest_audit

        from screenshot_crawler.core.runner import CrawlerRunner

        expected_pages = int(
            os.environ.get("PICCOMA_PHASE07_MANIFEST_EXPECTED_PAGES", "24")
        )
        install_runner_manifest_audit(
            CrawlerRunner, Path(audit_path), expected_pages=expected_pages
        )
