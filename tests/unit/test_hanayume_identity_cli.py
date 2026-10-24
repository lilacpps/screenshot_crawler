from pathlib import Path

import pytest

from screenshot_crawler import cli
from screenshot_crawler.catalog import (
    CatalogError,
    CatalogService,
    ItemInput,
    SourceInput,
    SourceTargetInput,
    WorkInput,
)

WORK_ID = "ca6472995ecea"
OLD_ID = "90fac353b1178"
NEW_ID = "5fa301a1e55e3"


def _catalog(path: Path) -> CatalogService:
    service = CatalogService(path)
    work = service.create_work(WorkInput(work_key="ng-life", title="NG LIFE"))
    item = service.create_item(ItemInput(item_title="scene1"), work_id=work.id)
    source = service.create_source(
        SourceInput(site="hanayume", external_id=f"{WORK_ID}:{OLD_ID}", discovery_key="ng-life"),
        item_id=item.id,
    )
    service.create_source_target(
        SourceTargetInput(
            backend="web", locator=f"https://hanayume.com/episodes/{OLD_ID}"
        ),
        source_id=source.id,
    )
    return service


def _args(path: Path, *mode: str):
    return cli._parser().parse_args([
        "catalog", "source-identity", "--catalog", str(path), "--site", "hanayume",
        "--work-key", "ng-life", "--old-external-id", f"{WORK_ID}:{OLD_ID}",
        "--new-external-id", f"{WORK_ID}:{NEW_ID}", "--new-url",
        f"https://hanayume.com/episodes/{NEW_ID}", "--reason", "native API proof",
        *mode,
    ])


def test_cli_dry_run_token_then_apply_updates_current_identity(tmp_path: Path, capsys) -> None:
    path = tmp_path / "catalog.sqlite"
    service = _catalog(path)
    cli._run_catalog(_args(path, "--dry-run"))
    output = capsys.readouterr().out
    token = next(line.split(": ", 1)[1] for line in output.splitlines() if "plan_token:" in line)
    cli._run_catalog(_args(path, "--apply", "--plan-token", token))
    assert service.find_source("hanayume", f"{WORK_ID}:{OLD_ID}") is None
    assert service.find_source("hanayume", f"{WORK_ID}:{NEW_ID}") is not None


def test_cli_rejects_mismatched_series_prefix(tmp_path: Path) -> None:
    path = tmp_path / "catalog.sqlite"
    _catalog(path)
    args = _args(path, "--dry-run")
    args.new_external_id = f"0000000000001:{NEW_ID}"
    with pytest.raises(CatalogError, match="work-prefixed"):
        cli._run_catalog(args)
