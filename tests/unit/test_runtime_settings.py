from __future__ import annotations

from pathlib import Path

import pytest

from screenshot_crawler.runtime_settings import (
    DEFAULT_DISCOVERY_INTER_TARGET_DELAY_MS,
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
        "    discovery_inter_target_delay_ms: 4500\n"
        "    work_ticket_cooldown_hours: 23\n",
        encoding="utf-8",
    )

    settings = load_runtime_settings(path)

    assert settings.for_site("magapoke") == SiteRuntimeSettings(
        page_turn_delay_ms=0,
        inter_candidate_delay_ms=0,
        work_ticket_cooldown_hours=23,
        discovery_inter_target_delay_ms=4500,
    )
    assert settings.for_site("mangaone").page_turn_delay_ms == DEFAULT_PAGE_TURN_DELAY_MS
    assert settings.for_site("mangaone").discovery_inter_target_delay_ms == (
        DEFAULT_DISCOVERY_INTER_TARGET_DELAY_MS
    )
    assert settings.for_site("mangaone").inter_candidate_delay_ms == (
        DEFAULT_INTER_CANDIDATE_DELAY_MS
    )


def test_runtime_settings_missing_file_uses_safe_defaults(tmp_path: Path) -> None:
    settings = load_runtime_settings(tmp_path / "missing.yaml")

    assert settings.for_site("unknown") == SiteRuntimeSettings()
    assert settings.for_site("unknown").discovery_inter_target_delay_ms == 3000
    assert settings.for_site("unknown").page_turn_delay_ms == DEFAULT_PAGE_TURN_DELAY_MS
    assert settings.for_site("unknown").inter_candidate_delay_ms == (
        DEFAULT_INTER_CANDIDATE_DELAY_MS
    )


def test_distributed_discovery_delays_cover_all_registered_sites() -> None:
    from screenshot_crawler.cli import _discovery_registry

    settings = load_runtime_settings(Path(__file__).parents[2] / "crawler.yaml")
    overrides = {"hanayume": 10000, "herosweb": 5000, "younganimal": 5000}
    for site in _discovery_registry().sites():
        assert site in settings.sites
        assert settings.for_site(site).discovery_inter_target_delay_ms == overrides.get(site, 3000)


def test_distributed_crawler_yaml_resolves_site_overrides() -> None:
    settings = load_runtime_settings(Path(__file__).parents[2] / "crawler.yaml")

    assert settings.for_site("piccoma") == SiteRuntimeSettings(
        page_turn_delay_ms=200,
        inter_candidate_delay_ms=3000,
        stop_on_http_403=True,
        stop_on_http_429=True,
        stop_on_challenge=True,
        stop_on_captcha=True,
    )
    assert settings.for_site("magapoke").page_turn_delay_ms == 1500
    assert settings.for_site("magapoke").inter_candidate_delay_ms == 6000
    assert settings.for_site("mangaone").page_turn_delay_ms == 1000
    assert settings.for_site("bookwalker").page_turn_delay_ms == 0
    assert settings.for_site("herosweb") == SiteRuntimeSettings(
        page_turn_delay_ms=1500,
        inter_candidate_delay_ms=5000,
        stop_on_http_403=True,
        stop_on_http_429=True,
        stop_on_challenge=True,
        stop_on_captcha=True,
        discovery_inter_target_delay_ms=5000,
    )


@pytest.mark.parametrize("site", ["piccoma", "ebookjapan"])
@pytest.mark.parametrize("field", ["page_turn_delay_ms", "discovery_inter_target_delay_ms"])
def test_runtime_settings_allow_explicit_zero_override(
    tmp_path: Path, site: str, field: str
) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        f"sites:\n  {site}:\n    {field}: 0\n",
        encoding="utf-8",
    )

    assert getattr(load_runtime_settings(path).for_site(site), field) == 0


@pytest.mark.parametrize(
    "field_value",
    [-1, True, "1000", 1.5],
)
@pytest.mark.parametrize("field", ["page_turn_delay_ms", "discovery_inter_target_delay_ms"])
def test_runtime_settings_reject_invalid_delay_values(
    tmp_path: Path, field_value: object, field: str
) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        f"sites:\n  mangaone:\n    {field}: {field_value!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeSettingsError, match=field):
        load_runtime_settings(path)


def test_runtime_settings_rejects_invalid_yaml_shapes(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text("sites: []\n", encoding="utf-8")

    with pytest.raises(RuntimeSettingsError, match="sites"):
        load_runtime_settings(path)


def test_runtime_settings_accepts_all_known_site_settings(tmp_path: Path) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        "sites:\n"
        "  magapoke:\n"
        "    page_turn_delay_ms: 0\n"
        "    inter_candidate_delay_ms: 0\n"
        "    stop_on_http_403: false\n"
        "    stop_on_http_429: true\n"
        "    stop_on_challenge: false\n"
        "    stop_on_captcha: true\n"
        "    work_ticket_cooldown_hours: 23\n",
        encoding="utf-8",
    )

    assert load_runtime_settings(path).for_site("magapoke") == SiteRuntimeSettings(
        page_turn_delay_ms=0,
        inter_candidate_delay_ms=0,
        stop_on_http_403=False,
        stop_on_http_429=True,
        stop_on_challenge=False,
        stop_on_captcha=True,
        work_ticket_cooldown_hours=23,
    )


@pytest.mark.parametrize("unknown_key", ["unknown_setting", "page_turn_dealy_ms"])
def test_runtime_settings_rejects_unknown_site_settings(
    tmp_path: Path, unknown_key: str
) -> None:
    path = tmp_path / "crawler.yaml"
    path.write_text(
        "sites:\n"
        "  magapoke:\n"
        f"    {unknown_key}: 1000\n"
        "    page_turn_delay_ms: 0\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeSettingsError,
        match=rf"^Unknown crawler\.yaml setting: sites\.magapoke\.{unknown_key}$",
    ):
        load_runtime_settings(path)
