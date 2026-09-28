from pathlib import Path

import pytest

from screenshot_crawler.watchlist import (
    DiscoveryScope,
    DuplicateWatchlistKeyError,
    InvalidWatchlistError,
    WatchlistService,
    WatchlistTargetNotFoundError,
)


def add_target(service: WatchlistService, **overrides: object):
    values = {
        "key": "one",
        "work_key": "work-one",
        "site": "mangaone",
        "url": "https://example.invalid/one",
        "label": "作品A",
    }
    values.update(overrides)
    return service.add(**values)


def test_missing_watchlist_is_empty_and_add_roundtrips_v3_fields(tmp_path: Path) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")
    assert service.list_targets() == []
    added = add_target(service)
    assert added.work_key == "work-one"
    assert added.label == "作品A"
    assert service.get("one") == added
    written = (tmp_path / "watchlist.yaml").read_text(encoding="utf-8")
    assert "work_key: work-one" in written
    assert "label: 作品A" in written
    assert "discovery_scope" not in written


def test_existing_scope_less_yaml_loads_as_unbounded(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    enabled: true\n"
        "    label: 作品A\n",
        encoding="utf-8",
    )

    loaded = WatchlistService(path).get("one")

    assert loaded.discovery_scope is None


@pytest.mark.parametrize(
    ("scope_yaml", "expected"),
    [
        (
            ("discovery_scope:\n"
             "      from_url: https://example.invalid/from\n"),
            DiscoveryScope(from_url="https://example.invalid/from"),
        ),
        (
            ("discovery_scope:\n"
             "      through_url: https://example.invalid/through\n"),
            DiscoveryScope(through_url="https://example.invalid/through"),
        ),
        (
            ("discovery_scope:\n"
             "      from_url: https://example.invalid/from\n"
             "      through_url: https://example.invalid/through\n"),
            DiscoveryScope(
                from_url="https://example.invalid/from",
                through_url="https://example.invalid/through",
            ),
        ),
    ],
)
def test_discovery_scope_forms_parse(
    tmp_path: Path, scope_yaml: str, expected: DiscoveryScope
) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    enabled: true\n"
        "    label: 作品A\n"
        f"    {scope_yaml}",
        encoding="utf-8",
    )

    assert WatchlistService(path).get("one").discovery_scope == expected


@pytest.mark.parametrize(
    "scope_yaml",
    [
        "discovery_scope: []\n",
        "discovery_scope: null\n",
        "discovery_scope: {}\n",
        "discovery_scope:\n      from_url: null\n",
        "discovery_scope:\n      through_url: ''\n",
        "discovery_scope:\n      from_url: '  '\n",
        "discovery_scope:\n      through_url: 123\n",
    ],
)
def test_invalid_discovery_scope_is_rejected(tmp_path: Path, scope_yaml: str) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    enabled: true\n"
        "    label: 作品A\n"
        f"    {scope_yaml}",
        encoding="utf-8",
    )

    with pytest.raises(InvalidWatchlistError, match="discovery_scope"):
        WatchlistService(path).list_targets()


def test_enable_disable_and_reload_preserve_discovery_scope(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    enabled: true\n"
        "    label: 作品A\n"
        "    discovery_scope:\n"
        "      from_url: https://example.invalid/from\n"
        "      through_url: https://example.invalid/through\n",
        encoding="utf-8",
    )
    service = WatchlistService(path)

    disabled = service.disable("one")
    assert disabled.discovery_scope == DiscoveryScope(
        from_url="https://example.invalid/from",
        through_url="https://example.invalid/through",
    )
    service.enable("one")
    reloaded = WatchlistService(path).get("one")

    assert reloaded.enabled is True
    assert reloaded.discovery_scope == disabled.discovery_scope
    written = path.read_text(encoding="utf-8")
    assert "discovery_scope:" in written
    assert "from_url: https://example.invalid/from" in written
    assert "through_url: https://example.invalid/through" in written


def test_same_work_key_can_be_shared_but_key_must_be_unique(tmp_path: Path) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")
    first = add_target(service)
    second = add_target(
        service,
        key="two",
        site="bookwalker",
        url="https://example.invalid/two",
    )
    assert [target.work_key for target in service.list_targets()] == ["work-one", "work-one"]
    assert second.site != first.site
    with pytest.raises(DuplicateWatchlistKeyError):
        add_target(service)


def test_enable_disable_preserves_identity_fields(tmp_path: Path) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")
    original = add_target(service)
    disabled = service.disable(original.key)
    assert disabled == original.__class__(
        key=original.key,
        work_key=original.work_key,
        site=original.site,
        url=original.url,
        label=original.label,
        enabled=False,
    )
    enabled = service.enable(original.key)
    assert enabled == original
    with pytest.raises(WatchlistTargetNotFoundError):
        service.remove("missing")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("key", ""),
        ("work_key", " "),
        ("site", ""),
        ("url", " \t"),
        ("label", ""),
    ],
)
def test_add_rejects_empty_required_fields(
    tmp_path: Path, field: str, value: str
) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")
    with pytest.raises(InvalidWatchlistError, match=field):
        add_target(service, **{field: value})


@pytest.mark.parametrize(
    "content",
    [
        "targets: [",
        "{}",
        "targets: {}",
        "targets:\n  - key: one\n    site: mangaone\n    url: https://example.invalid/one\n",
        "targets:\n  - key: one\n    work_key: work\n    site: mangaone\n    url: https://example.invalid/one\n    label: null\n",
        "targets:\n  - key: one\n    work_key: work\n    site: mangaone\n    url: https://example.invalid/one\n    label: 作品\n    enabled: 1\n",
    ],
)
def test_invalid_watchlist_is_rejected(tmp_path: Path, content: str) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(InvalidWatchlistError):
        WatchlistService(path).list_targets()


def test_duplicate_keys_in_yaml_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - {key: one, work_key: work, site: mangaone, url: https://example.invalid/one, label: A}\n"
        "  - {key: one, work_key: work, site: mangaone, url: https://example.invalid/two, label: B}\n",
        encoding="utf-8",
    )
    with pytest.raises(DuplicateWatchlistKeyError):
        WatchlistService(path).list_targets()
