"""Offline safety checks for the research-only Phase 07 CLI launcher."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import phase07_cli_driver as driver


class Phase07CliDriverSafetyTests(unittest.TestCase):
    def test_rejects_duplicate_and_equals_output_options(self) -> None:
        for args in (
            ["crawl", "--output-dir", "a", "--output-dir", "b"],
            ["batch", "run", "--catalog=a.sqlite"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                driver._check_flag_tokens(args)

    def test_rejects_abbreviations_and_env_or_grant_operations(self) -> None:
        for args in (
            ["crawl", "--diagnostics", "x"],
            ["crawl", "--env-file", "secrets.env"],
            ["batch", "run", "--grant-only", "ticket"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                driver._check_flag_tokens(args)

    def test_requires_piccoma_and_isolated_paths_from_resolved_parser(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            output_root = root / "piccoma_performance"
            phase_root = output_root / "phase07_fixture"
            run_dir = phase_root / "manual"
            config = phase_root / "crawler.yaml"
            config.parent.mkdir(parents=True)
            config.write_text("sites: {piccoma: {page_turn_delay_ms: 200}}\n")
            values = {
                "command": "crawl", "site": "piccoma",
                "access_strategy": "direct",
                "runtime_settings": {
                    "page_turn_delay_ms": 200,
                    "stop_on_http_403": True,
                    "stop_on_http_429": True,
                    "stop_on_challenge": True,
                    "stop_on_captcha": True,
                },
                "crawler_config": str(config),
                "cdp_endpoint": "http://127.0.0.1:9222",
                "output_dir": "crawl", "diagnostics_dir": "diagnostics",
                "library_dir": "library", "max_pages": "12",
            }
            args = [
                "crawl", "--site", "piccoma", "--access-strategy", "direct",
                "--output-dir", "crawl", "--diagnostics-dir", "diagnostics",
                "--library-dir", "library",
            ]
            with patch.object(driver, "ALLOWED_OUTPUT_ROOT", output_root):
                safe_paths = driver._validate_resolved_cli(
                    args, values, config, run_dir, phase_root
                )
                self.assertEqual(set(safe_paths), {
                    "--output-dir", "--diagnostics-dir", "--library-dir"
                })
                self.assertEqual(
                    safe_paths["--diagnostics-dir"], phase_root / "manual" / "diagnostics"
                )
                wrong_site = {**values, "site": "mangaone"}
                with self.assertRaises(ValueError):
                    driver._validate_resolved_cli(
                        args, wrong_site, config, run_dir, phase_root
                    )
                escaped = {**values, "diagnostics_dir": str(root / "diagnostics")}
                with self.assertRaises(ValueError):
                    driver._validate_resolved_cli(
                        args, escaped, config, run_dir, phase_root
                    )
                for stop_flag in driver._REQUIRED_TRUE_STOP_FLAGS:
                    with self.subTest(stop_flag=stop_flag):
                        settings = {**values["runtime_settings"], stop_flag: False}
                        changed = {**values, "runtime_settings": settings}
                        with self.assertRaisesRegex(ValueError, stop_flag):
                            driver._validate_resolved_cli(
                                args, changed, config, run_dir, phase_root
                            )

    def test_rejects_catalog_outside_phase_output_and_nonisolated_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            output_root = root / "piccoma_performance"
            phase_root = output_root / "phase07_fixture"
            run_dir = phase_root / "batch"
            config = phase_root / "crawler.yaml"
            catalog = phase_root / "catalog.sqlite"
            config.parent.mkdir(parents=True)
            config.write_text("sites: {piccoma: {page_turn_delay_ms: 200}}\n")
            catalog.write_bytes(b"isolated fixture")
            args = [
                "batch", "run", "--site", "piccoma", "--catalog", str(catalog),
                "--output-root", "crawls", "--library-dir", "library",
            ]
            values = {
                "command": "batch", "batch_action": "run", "site": "piccoma",
                "runtime_settings": {
                    "page_turn_delay_ms": 200,
                    "stop_on_http_403": True,
                    "stop_on_http_429": True,
                    "stop_on_challenge": True,
                    "stop_on_captcha": True,
                },
                "catalog": str(catalog), "output_root": "crawls",
                "library_dir": "library", "crawler_config": str(config),
                "cdp_endpoint": "http://127.0.0.1:9222", "max_pages": "1000",
            }
            with patch.object(driver, "ALLOWED_OUTPUT_ROOT", output_root):
                paths = driver._validate_resolved_cli(
                    args, values, config, run_dir, phase_root
                )
                self.assertEqual(paths["--catalog"], catalog)
                misplaced = {**values, "catalog": str(root / "catalog.sqlite")}
                with self.assertRaises(ValueError):
                    driver._validate_resolved_cli(
                        args, misplaced, config, run_dir, phase_root
                    )

    def test_module_hash_match_and_terminal_classification(self) -> None:
        module_paths = {
            "screenshot_crawler.site_adapters.piccoma.adapter":
                "src/screenshot_crawler/site_adapters/piccoma/adapter.py",
            "screenshot_crawler.site_adapters.piccoma.native_capture":
                "src/screenshot_crawler/site_adapters/piccoma/native_capture.py",
            "screenshot_crawler.runtime_settings":
                "src/screenshot_crawler/runtime_settings.py",
            "screenshot_crawler.cli": "src/screenshot_crawler/cli.py",
        }
        expected = {
            name: {"module_path": module_path, "sha256": name}
            for name, module_path in module_paths.items()
        }
        loaded = {
            short: {
                "module_path": str(Path("source") / expected[full]["module_path"]),
                "sha256": expected[full]["sha256"],
            }
            for short, full in (
                ("piccoma_adapter", "screenshot_crawler.site_adapters.piccoma.adapter"),
                ("piccoma_native_capture", "screenshot_crawler.site_adapters.piccoma.native_capture"),
                ("runtime_settings", "screenshot_crawler.runtime_settings"),
                ("cli", "screenshot_crawler.cli"),
            )
        }
        self.assertTrue(driver._loaded_modules_match(expected, loaded, Path("source")))
        loaded["piccoma_native_capture"]["sha256"] = "wrong"
        self.assertFalse(driver._loaded_modules_match(expected, loaded, Path("source")))
        self.assertEqual(
            driver._terminal_contract("crawl", "12", True),
            "bounded_manual_probe_never_counts_as_END",
        )
        self.assertEqual(
            driver._terminal_contract("batch", "12", True),
            "bounded_batch_probe_never_counts_as_END",
        )
        self.assertEqual(
            driver._terminal_contract("batch", "1000", False),
            "batch_requires_independent_explicit_END_and_artifact_audit",
        )
        self.assertEqual(driver._wrapper_exit_code(7, True, True), 7)
        self.assertEqual(driver._wrapper_exit_code(0, True, False), 2)

    def test_cli_output_only_retains_sanitized_terminal_and_exception_data(self) -> None:
        safe = driver._sanitize_cli_output(
            "Saved 24 pages; stopped at END.\nArchive saved to private-path.zip",
            "MaxPagesExceededError: https://example.invalid/?sig=secret\n",
        )
        self.assertEqual(safe["reported_saved_pages"], 24)
        self.assertEqual(safe["reported_stop_reason"], "END")
        self.assertEqual(safe["sanitized_exception_type"], "MaxPagesExceededError")
        self.assertFalse(safe["stdout_stderr_persisted"])
        self.assertNotIn("private-path", str(safe))
        self.assertNotIn("secret", str(safe))

    def test_selected_runtime_loader_uses_true_defaults_and_rejects_each_false_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            phase_root = Path(temp) / "piccoma_performance" / "phase07_settings"
            phase_root.mkdir(parents=True)
            config = phase_root / "crawler.yaml"
            cli_args = [
                "crawl", "--site", "piccoma", "--url",
                "https://piccoma.com/web/viewer/28600/1910027",
                "--access-strategy", "direct", "--max-pages", "12",
                "--output-dir", str(phase_root / "run" / "crawl"),
                "--diagnostics-dir", str(phase_root / "run" / "diagnostics"),
                "--library-dir", str(phase_root / "run" / "library"),
                "--crawler-config", str(config),
                "--cdp-endpoint", "http://127.0.0.1:9222",
            ]
            run_dir = phase_root / "run"
            safe_config = "sites: {piccoma: {page_turn_delay_ms: 200}}\n"
            with patch.object(driver, "ALLOWED_OUTPUT_ROOT", phase_root.parent):
                config.write_text(safe_config, encoding="utf-8")
                resolved = driver._parse_with_selected_source(
                    Path(sys.executable), driver.REPO_ROOT / "src",
                    driver.REPO_ROOT, cli_args,
                )
                settings = resolved["runtime_settings"]
                self.assertEqual(settings["page_turn_delay_ms"], 200)
                for stop_flag in driver._REQUIRED_TRUE_STOP_FLAGS:
                    self.assertIs(settings[stop_flag], True)
                driver._validate_resolved_cli(
                    cli_args, resolved, config, run_dir, phase_root
                )

                for stop_flag in driver._REQUIRED_TRUE_STOP_FLAGS:
                    with self.subTest(stop_flag=stop_flag):
                        config.write_text(
                            f"sites: {{piccoma: {{page_turn_delay_ms: 200, {stop_flag}: false}}}}\n",
                            encoding="utf-8",
                        )
                        resolved_false = driver._parse_with_selected_source(
                            Path(sys.executable), driver.REPO_ROOT / "src",
                            driver.REPO_ROOT, cli_args,
                        )
                        with self.assertRaisesRegex(ValueError, stop_flag):
                            driver._validate_resolved_cli(
                                cli_args, resolved_false, config, run_dir, phase_root
                            )

    def test_selected_source_cli_parser_resolves_actual_site_and_outputs_offline(self) -> None:
        values = driver._parse_with_selected_source(
            Path(sys.executable), driver.REPO_ROOT / "src", driver.REPO_ROOT,
            [
                "crawl", "--site", "piccoma", "--url",
                "https://piccoma.com/web/viewer/28600/1910027",
                "--access-strategy", "direct", "--max-pages", "12",
                "--output-dir", "crawl", "--diagnostics-dir", "diagnostics",
                "--library-dir", "library", "--crawler-config", "crawler.yaml",
                "--cdp-endpoint", "http://127.0.0.1:9222",
            ],
        )
        self.assertEqual(values.get("command"), "crawl")
        self.assertEqual(values.get("site"), "piccoma")
        self.assertEqual(values.get("max_pages"), "12")
        self.assertEqual(values.get("cdp_endpoint"), "http://127.0.0.1:9222")

    def test_phase07_hook_loads_stock_cli_and_records_actual_source_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            trace_path = Path(temp) / "timings.json"
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join((
                str(driver.HOOK_ROOT), str(driver.RESEARCH_ROOT),
                str(driver.REPO_ROOT / "src"),
            ))
            env["PICCOMA_PHASE07_PROFILE"] = "1"
            env["PERF_TRACE_FILE"] = str(trace_path)
            env.pop("PERF_PROGRESS_FILE", None)
            run = subprocess.run(
                [sys.executable, "-m", "screenshot_crawler.cli", "--help"],
                cwd=driver.REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0)
            timings = json.loads(trace_path.read_text(encoding="utf-8"))
            expected = {
                name: {
                    "module_path": str(path.relative_to(driver.REPO_ROOT)).replace("\\", "/"),
                    "sha256": driver._sha256(path),
                }
                for name, path in {
                    "screenshot_crawler.site_adapters.piccoma.adapter":
                        driver.REPO_ROOT / "src/screenshot_crawler/site_adapters/piccoma/adapter.py",
                    "screenshot_crawler.site_adapters.piccoma.native_capture":
                        driver.REPO_ROOT / "src/screenshot_crawler/site_adapters/piccoma/native_capture.py",
                    "screenshot_crawler.runtime_settings":
                        driver.REPO_ROOT / "src/screenshot_crawler/runtime_settings.py",
                    "screenshot_crawler.cli": driver.REPO_ROOT / "src/screenshot_crawler/cli.py",
                }.items()
            }
            self.assertTrue(
                driver._loaded_modules_match(
                    expected, timings["source_modules"], driver.REPO_ROOT
                )
            )


if __name__ == "__main__":
    unittest.main()
