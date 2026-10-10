"""Offline tests for the opt-in prepackage manifest evidence hook."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import phase07_manifest_audit as audit


def _manifest(page_count: int = 2) -> dict[str, object]:
    pages = []
    for sequence in range(1, page_count + 1):
        pages.append({
            "sequence": sequence,
            "file": f"page-{sequence:04}.webp",
            "mime_type": "image/webp",
            "file_extension": ".webp",
            "source_url": "https://sensitive.example/signed?secret=value",
            "identity": {
                "page_id": f"p{sequence}",
                "source_id": "28600:1910027",
            },
            "metadata": {"piccoma_capture": {
                "method": "native_tile_replay_lossless_webp",
                "source_native": True,
                "source_mime": "image/jpeg",
                "source_backdrop": "verified_solid_white",
                "output_format": "image/webp",
                "output_lossless": True,
                "fallback_reason": None,
                "encoding_fallback_reason": None,
                "page_count": page_count,
                "request_url": "https://sensitive.example/secret",
            }},
        })
    return {
        "source_url": "https://sensitive.example/signed?secret=value",
        "content_context": {"title": "private title"},
        "pages": pages,
    }


class Phase07ManifestAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "output" / "piccoma_performance"
        self.phase = self.root / "phase07_fixture"
        self.phase.mkdir(parents=True)
        self.allowed_patch = patch.object(audit, "ALLOWED_OUTPUT_ROOT", self.root.resolve())
        self.allowed_patch.start()

    def tearDown(self) -> None:
        self.allowed_patch.stop()
        self.temp.cleanup()

    def test_reads_once_and_emits_only_whitelisted_url_free_evidence(self) -> None:
        output = self.phase / "crawl"
        output.mkdir()
        manifest_path = output / "manifest.json"
        manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
        report_path = self.phase / "manifest_audit.json"

        report = audit.audit_manifest_file(output, report_path, expected_pages=2)
        saved = json.loads(report_path.read_text(encoding="utf-8"))
        serialized = json.dumps(saved)

        self.assertTrue(report["audit_passed"])
        self.assertEqual(report["manifest_read_count"], 1)
        self.assertEqual(report["sequence"], [1, 2])
        self.assertEqual(report["page_ids"], ["p1", "p2"])
        self.assertTrue(report["source_identity_consistent"])
        self.assertNotIn("source_url", serialized)
        self.assertNotIn("request_url", serialized)
        self.assertNotIn("signed", serialized)
        self.assertNotIn("private title", serialized)

    def test_invalid_page_contract_writes_false_without_raw_input(self) -> None:
        output = self.phase / "crawl"
        output.mkdir()
        raw = _manifest()
        raw["pages"][0]["metadata"]["piccoma_capture"]["output_lossless"] = False
        (output / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
        report = audit.audit_manifest_file(
            output, self.phase / "manifest_audit.json", expected_pages=2
        )
        self.assertIs(report["audit_passed"], False)
        self.assertIn("page_contract_mismatch", report["failure_codes"])
        self.assertNotIn("source_url", json.dumps(report))

    def test_runner_audits_after_end_before_the_packager_call(self) -> None:
        output = self.phase / "crawl"
        output.mkdir()
        (output / "manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
        report_path = self.phase / "manifest_audit.json"

        class FakeRunner:
            config = SimpleNamespace(output_dir=output)

            async def run(self, _page: object, _adapter: object) -> object:
                return SimpleNamespace(stop_state="end")

        audit.install_runner_manifest_audit(FakeRunner, report_path, expected_pages=2)
        result = asyncio.run(FakeRunner().run(None, None))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        packager_called = False

        def fake_packager() -> None:
            nonlocal packager_called
            self.assertTrue(report_path.is_file())
            self.assertTrue(report["audit_passed"])
            packager_called = True

        fake_packager()
        self.assertEqual(result.stop_state, "end")
        self.assertTrue(packager_called)

    def test_non_end_runner_writes_false_and_raises_before_packaging(self) -> None:
        output = self.phase / "crawl"
        output.mkdir()
        report_path = self.phase / "manifest_audit.json"

        class FakeRunner:
            config = SimpleNamespace(output_dir=output)

            async def run(self, _page: object, _adapter: object) -> object:
                return SimpleNamespace(stop_state="content")

        audit.install_runner_manifest_audit(FakeRunner, report_path, expected_pages=2)
        with self.assertRaisesRegex(RuntimeError, "phase07_prepackage_manifest_audit_failed"):
            asyncio.run(FakeRunner().run(None, None))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIs(report["audit_passed"], False)
        self.assertEqual(report["failure_code"], "runner_did_not_reach_end")
        self.assertEqual(report["manifest_read_count"], 0)


if __name__ == "__main__":
    unittest.main()
