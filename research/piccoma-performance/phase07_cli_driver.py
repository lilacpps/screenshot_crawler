"""Run an actual Piccoma CLI command with isolated, numeric-only profiling.

This wrapper intentionally does not persist CLI arguments or stdout/stderr:
they can contain viewer URLs or other sensitive site state. The caller passes
the ordinary `crawl` or `batch run` arguments after `--`; this script inserts
the selected source tree and the explicit runtime YAML path, then records only
sanitized process metadata and source hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_ROOT = Path(__file__).resolve().parent
HOOK_ROOT = RESEARCH_ROOT / "phase07_hook"
ALLOWED_OUTPUT_ROOT = (REPO_ROOT / "output" / "piccoma_performance").resolve()
SAFE_OPTIONS = {
    "--site", "--output-dir", "--diagnostics-dir", "--library-dir",
    "--catalog", "--output-root", "--crawler-config", "--cdp-endpoint",
    "--access-strategy", "--env-file", "--grant-only", "--keep-open",
}
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside_output(path: Path) -> bool:
    try:
        path.relative_to(ALLOWED_OUTPUT_ROOT)
        return True
    except ValueError:
        return False


def _phase_root(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate == ALLOWED_OUTPUT_ROOT:
            break
        if candidate.parent == ALLOWED_OUTPUT_ROOT and candidate.name.startswith("phase07_"):
            return candidate
    raise ValueError("path must belong to one isolated phase07_ output directory")


def _check_flag_tokens(cli_args: Sequence[str]) -> None:
    counts: dict[str, int] = {}
    for token in cli_args:
        if not token.startswith("--"):
            continue
        option, separator, _value = token.partition("=")
        if option in {"--env-file", "--grant-only", "--keep-open"}:
            raise ValueError(f"{option} is not allowed in isolated Phase 07 profiling")
        if option in SAFE_OPTIONS:
            if separator:
                raise ValueError(f"use the separate value form for {option}")
            counts[option] = counts.get(option, 0) + 1
            if counts[option] > 1:
                raise ValueError(f"repeated {option} is rejected")
        elif any(known.startswith(option) for known in SAFE_OPTIONS):
            raise ValueError("abbreviated safety-sensitive options are rejected")


def _parse_with_selected_source(
    python: Path, source_dir: Path, source_root: Path, cli_args: Sequence[str]
) -> dict[str, object]:
    parse_code = (
        "import json,sys; from screenshot_crawler.cli import _parser; "
        "from screenshot_crawler.runtime_settings import load_runtime_settings; "
        "args=_parser().parse_args(sys.argv[1:]); values=vars(args); "
        "settings=load_runtime_settings(values['crawler_config']).for_site('piccoma'); "
        "keys=('command','batch_action','site','output_dir','diagnostics_dir',"
        "'library_dir','catalog','output_root','crawler_config','cdp_endpoint',"
        "'max_pages','env_file','access_strategy','grant_only','keep_open'); "
        "print(json.dumps({key:str(values[key]) if values.get(key) is not None "
        "else None for key in keys if key in values} | {'runtime_settings': {"
        "'page_turn_delay_ms': settings.page_turn_delay_ms, "
        "'stop_on_http_403': settings.stop_on_http_403, "
        "'stop_on_http_429': settings.stop_on_http_429, "
        "'stop_on_challenge': settings.stop_on_challenge, "
        "'stop_on_captcha': settings.stop_on_captcha}}))"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_dir)
    env["PYTHONNOUSERSITE"] = "1"
    parsed = subprocess.run(
        [str(python), "-c", parse_code, *cli_args],
        cwd=source_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if parsed.returncode != 0:
        raise ValueError("selected source CLI parser rejected the arguments")
    try:
        values = json.loads(parsed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("selected source CLI parser returned invalid metadata") from exc
    if not isinstance(values, dict):
        raise TypeError("selected source CLI parser did not return a mapping")
    return values


def _validate_resolved_cli(
    cli_args: Sequence[str], values: dict[str, object], config: Path,
    run_dir: Path, phase_root: Path,
) -> dict[str, Path]:
    if cli_args.count("--site") != 1:
        raise ValueError("exactly one explicit --site is required")
    if values.get("site") != "piccoma":
        raise ValueError("only --site piccoma is allowed")
    if values.get("command") == "batch":
        if values.get("batch_action") != "run":
            raise ValueError("only the ordinary `batch run` command is accepted")
        if values.get("grant_only"):
            raise ValueError("grant-only Batch runs are outside Phase 07")
        required = ("--catalog", "--output-root", "--library-dir")
    elif values.get("command") == "crawl":
        if cli_args.count("--access-strategy") != 1:
            raise ValueError("exactly one explicit --access-strategy is required")
        if values.get("access_strategy") != "direct":
            raise ValueError("manual Piccoma profiling requires direct access intent")
        required = ("--output-dir", "--diagnostics-dir", "--library-dir")
    else:
        raise ValueError("only crawl or batch run can be profiled")

    if values.get("crawler_config") is None:
        raise ValueError("resolved crawler config is missing")
    settings = values.get("runtime_settings")
    if not isinstance(settings, dict):
        raise TypeError("selected runtime settings loader returned no settings")
    if type(settings.get("page_turn_delay_ms")) is not int or settings.get(
        "page_turn_delay_ms"
    ) != 200:
        raise ValueError("Phase 07 resolved page_turn_delay_ms must be 200")
    for field in _REQUIRED_TRUE_STOP_FLAGS:
        if settings.get(field) is not True:
            raise ValueError(f"Phase 07 resolved {field} must remain true")
    parsed_config = Path(str(values["crawler_config"]))
    if not parsed_config.is_absolute():
        parsed_config = run_dir / parsed_config
    if parsed_config.resolve() != config.resolve():
        raise ValueError("selected CLI resolved a different crawler config")
    endpoint = values.get("cdp_endpoint")
    if endpoint != "http://127.0.0.1:9222":
        raise ValueError("the shared local CDP endpoint must be explicit")

    paths: dict[str, Path] = {}
    for option in required:
        if cli_args.count(option) != 1:
            raise ValueError(f"exactly one explicit {option} is required")
        value = values.get(option[2:].replace("-", "_"))
        if not isinstance(value, str) or not value:
            raise ValueError(f"resolved value for {option} is missing")
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = run_dir / candidate
        candidate = candidate.resolve()
        if not _inside_output(candidate) or _phase_root(candidate) != phase_root:
            raise ValueError(f"{option} must stay inside this isolated Phase 07 output")
        if option == "--catalog" and not candidate.is_file():
            raise ValueError("Batch Catalog must be an existing isolated file")
        if option != "--catalog" and candidate.exists():
            raise ValueError(f"{option} already exists; refusing to overwrite")
        paths[option] = candidate
    output_paths = [path for option, path in paths.items() if option != "--catalog"]
    for index, path in enumerate(output_paths):
        for other in output_paths[index + 1:]:
            if path == other or path in other.parents or other in path.parents:
                raise ValueError("isolated output directories must not overlap")
    return paths


_REQUIRED_TRUE_STOP_FLAGS = (
    "stop_on_http_403", "stop_on_http_429", "stop_on_challenge", "stop_on_captcha"
)


def _loaded_modules_match(
    expected: dict[str, dict[str, str]],
    loaded: dict[str, object],
    source_root: Path,
) -> bool:
    names = {
        "piccoma_adapter": "screenshot_crawler.site_adapters.piccoma.adapter",
        "piccoma_native_capture": "screenshot_crawler.site_adapters.piccoma.native_capture",
        "runtime_settings": "screenshot_crawler.runtime_settings",
        "cli": "screenshot_crawler.cli",
    }
    if any(name not in expected for name in names.values()) or any(
        name not in loaded for name in names
    ):
        return False
    for loaded_name, expected_name in names.items():
        wanted = expected[expected_name]
        actual = loaded[loaded_name]
        if not isinstance(actual, dict):
            return False
        expected_path = (source_root / wanted["module_path"]).resolve()
        if Path(str(actual.get("module_path", ""))).resolve() != expected_path:
            return False
        if actual.get("sha256") != wanted["sha256"]:
            return False
    return True


def _terminal_contract(command: str, max_pages: object, explicit: bool) -> str:
    if command == "crawl":
        return "bounded_manual_probe_never_counts_as_END"
    try:
        bounded_limit = int(str(max_pages))
    except (TypeError, ValueError):
        bounded_limit = 1000
    if explicit and bounded_limit < 1000:
        return "bounded_batch_probe_never_counts_as_END"
    return "batch_requires_independent_explicit_END_and_artifact_audit"


def _wrapper_exit_code(process_exit_code: int, timings_present: bool,
                       sources_match: bool) -> int:
    if process_exit_code != 0:
        return process_exit_code
    return 0 if timings_present and sources_match else 2


def _sanitize_cli_output(stdout: str, stderr: str) -> dict[str, object]:
    saved = re.search(r"Saved ([0-9]+) pages; stopped at ([A-Za-z_]+)", stdout)
    exception_type = None
    for line in reversed(stderr.splitlines()):
        candidate = line.strip().split(":", 1)[0].rsplit(".", 1)[-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)", candidate):
            exception_type = candidate
            break
    return {
        "reported_saved_pages": int(saved.group(1)) if saved else None,
        "reported_stop_reason": saved.group(2) if saved else None,
        "sanitized_exception_type": exception_type,
        "stdout_stderr_persisted": False,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--source-root", required=True, type=Path,
                        help="checkout/copy containing src/screenshot_crawler")
    parser.add_argument("--source-label", required=True,
                        help="non-sensitive label such as object-baseline or json-current")
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--crawler-config", required=True, type=Path)
    parser.add_argument("cli_args", nargs=argparse.REMAINDER,
                        help="ordinary CLI arguments, beginning with crawl or batch run")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    source_root = args.source_root.resolve()
    python = args.python.resolve()
    run_dir = args.run_dir.resolve()
    crawler_config = args.crawler_config.resolve()
    source_dir = source_root / "src"
    if not (source_dir / "screenshot_crawler").is_dir():
        raise SystemExit("source-root must contain src/screenshot_crawler")
    if not _inside_output(run_dir) or run_dir == ALLOWED_OUTPUT_ROOT:
        raise SystemExit("run-dir must be a new isolated path below output/piccoma_performance")
    if run_dir.exists():
        raise SystemExit("run-dir already exists; refusing to overwrite evidence")
    if not crawler_config.is_file():
        raise SystemExit("crawler-config must be an existing isolated YAML file")
    try:
        phase_root = _phase_root(run_dir)
        if _phase_root(crawler_config.resolve()) != phase_root:
            raise ValueError("crawler config must be inside the same Phase 07 output")
    except (TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if not python.is_file():
        raise SystemExit("python executable does not exist")

    cli_args = list(args.cli_args)
    if cli_args and cli_args[0] == "--":
        cli_args = cli_args[1:]
    if not cli_args or cli_args[0] not in {"crawl", "batch"}:
        raise SystemExit("CLI arguments must begin with crawl or batch")
    try:
        _check_flag_tokens(cli_args)
    except (TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if "--crawler-config" in cli_args:
        raise SystemExit("pass the isolated YAML only through --crawler-config option")
    cli_args.extend(["--crawler-config", str(crawler_config)])
    if "--cdp-endpoint" not in cli_args:
        cli_args.extend(["--cdp-endpoint", "http://127.0.0.1:9222"])

    try:
        resolved = _parse_with_selected_source(python, source_dir, source_root, cli_args)
        paths = _validate_resolved_cli(
            cli_args, resolved, crawler_config, run_dir, phase_root
        )
    except (TypeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    run_dir.mkdir(parents=True)
    (run_dir / ".env").write_text("", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(HOOK_ROOT), str(RESEARCH_ROOT), str(source_dir)))
    env["PICCOMA_PHASE07_PROFILE"] = "1"
    env["PERF_TRACE_FILE"] = str(run_dir / "timings.json")
    env["PERF_PROGRESS_FILE"] = str(run_dir / "page-progress.json")
    # Do not let inherited credentials or per-user environment files affect an
    # isolated manual probe; normal exact-free classification stays site-led.
    env.pop("PICCOMA_PHASE07_RESOLVED_SETTINGS", None)

    command = [str(python), "-m", "screenshot_crawler.cli", *cli_args]
    start = time.perf_counter()
    completed = subprocess.run(command, cwd=run_dir, env=env,
                               capture_output=True, text=True,
                               check=False)
    elapsed_s = time.perf_counter() - start
    cli_output = _sanitize_cli_output(completed.stdout, completed.stderr)

    module_paths = {
        name: source_dir / "screenshot_crawler" / Path(
            *name.split(".")[1:]
        ).with_suffix(".py")
        for name in (
            "screenshot_crawler.site_adapters.piccoma.adapter",
            "screenshot_crawler.site_adapters.piccoma.native_capture",
            "screenshot_crawler.runtime_settings",
            "screenshot_crawler.cli",
        )
    }
    sources = {
        name: {
            "module_path": str(path.relative_to(source_root)).replace("\\", "/"),
            "sha256": _sha256(path),
        }
        for name, path in module_paths.items() if path.is_file()
    }
    timings_exists = (run_dir / "timings.json").is_file()
    loaded_modules: dict[str, object] = {}
    if timings_exists:
        try:
            timings = json.loads((run_dir / "timings.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timings = {}
        candidate_modules = timings.get("source_modules")
        if isinstance(candidate_modules, dict):
            loaded_modules = candidate_modules
    result = {
        "command_kind": "manual_crawl" if resolved.get("command") == "crawl" else "batch_run",
        "source_label": args.source_label,
        "source_root": str(source_root),
        "source_modules": sources,
        "loaded_source_modules": loaded_modules,
        "loaded_source_matches_selected": _loaded_modules_match(
            sources, loaded_modules, source_root
        ),
        "crawler_config_name": crawler_config.name,
        "crawler_config_sha256": _sha256(crawler_config),
        "resolved_cli_config_argument": "--crawler-config",
        "resolved_site": resolved.get("site"),
        "resolved_runtime_settings": resolved.get("runtime_settings"),
        "resolved_output_paths": {key: str(value) for key, value in paths.items()},
        "requested_max_pages": resolved.get("max_pages"),
        "max_pages_explicit": "--max-pages" in cli_args,
        "terminal_contract": _terminal_contract(
            str(resolved.get("command")), resolved.get("max_pages"),
            "--max-pages" in cli_args,
        ),
        "end_verified": False,
        "process_wall_s": elapsed_s,
        "process_exit_code": completed.returncode,
        **cli_output,
        "timing_hook_output_present": timings_exists,
    }
    (run_dir / "phase07_cli_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    return _wrapper_exit_code(
        completed.returncode, timings_exists,
        bool(result["loaded_source_matches_selected"]),
    )


if __name__ == "__main__":
    raise SystemExit(main())
