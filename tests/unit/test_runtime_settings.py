from __future__ import annotations

from pathlib import Path

import pytest

from screenshot_crawler.runtime_settings import (
    DEFAULT_INTER_CANDIDATE_DELAY_MS,
    DEFAULT_PAGE_TURN_DELAY_MS,
    RuntimeSettingsError,
    SiteRuntimeSettings,
    load_runtime_settings,
)


def test_runtime_settings_load_and_resolve_site_defaults(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        "sites:\n"
        "  magapoke:\n"
        "    page_turn_delay_ms: 0\n"
        "    inter_candidate_delay_ms: 0\n"
        "    work_ticket_cooldown_hours: 23\n",
        encoding="utf-8",
    )

    settings = load_runtime_settings(path)

    assert settings.for_site("magapoke") == SiteRuntimeSettings(
        page_turn_delay_ms=0,
        inter_candidate_delay_ms=0,
        work_ticket_cooldown_hours=23,
    )
    assert settings.for_site("mangaone").page_turn_delay_ms == DEFAULT_PAGE_TURN_DELAY_MS
    assert settings.for_site("mangaone").inter_candidate_delay_ms == (
        DEFAULT_INTER_CANDIDATE_DELAY_MS
    )


def test_runtime_settings_missing_file_uses_safe_defaults(tmp_path: Path) -> None:
    settings = load_runtime_settings(tmp_path / "missing.yaml")

    assert settings.for_site("unknown") == SiteRuntimeSettings()
    assert settings.for_site("unknown").page_turn_delay_ms > 0
    assert settings.for_site("unknown").inter_candidate_delay_ms > 0


@pytest.mark.parametrize(
    "field_value",
    [-1, True, "1000", 1.5],
)
def test_runtime_settings_reject_invalid_delay_values(
    tmp_path: Path, field_value: object
) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        f"sites:\n  mangaone:\n    page_turn_delay_ms: {field_value!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeSettingsError, match="page_turn_delay_ms"):
        load_runtime_settings(path)


def test_runtime_settings_rejects_invalid_yaml_shapes(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text("sites: []\n", encoding="utf-8")

    with pytest.raises(RuntimeSettingsError, match="sites"):
        load_runtime_settings(path)
