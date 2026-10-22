from dataclasses import replace
from pathlib import Path

import pytest

from screenshot_crawler.watchlist import (
    DiscoveryScope,
    DuplicateWatchlistKeyError,
    InvalidWatchlistError,
    WatchlistError,
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


def test_flow_empty_targets_and_omitted_enabled_remain_writable(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text("targets: []\n", encoding="utf-8")
    service = WatchlistService(path)
    add_target(service)
    assert service.get("one").enabled is True

    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    label: One\n",
        encoding="utf-8",
    )
    assert service.disable("one").enabled is False
    assert WatchlistService(path).get("one").enabled is False


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


def test_add_rewrite_preserves_existing_discovery_scope(tmp_path: Path) -> None:
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
        "      from_url: https://example.invalid/from\n",
        encoding="utf-8",
    )
    service = WatchlistService(path)

    add_target(service, key="two", work_key="work-two", label="作品B")

    assert service.get("one").discovery_scope == DiscoveryScope(
        from_url="https://example.invalid/from"
    )
    assert service.get("two").discovery_scope is None


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


def test_archive_order_is_roundtripped_and_required_for_every_key_in_work(
    tmp_path: Path,
) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: shared\n"
        "    site: zebrak\n"
        "    url: https://example.invalid/one\n"
        "    enabled: false\n"
        "    label: One\n"
        "    archive_order: 1\n"
        "  - key: two\n"
        "    work_key: shared\n"
        "    site: bookwalker\n"
        "    url: https://example.invalid/two\n"
        "    label: Two\n"
        "    archive_order: 2\n",
        encoding="utf-8",
    )
    service = WatchlistService(path)
    assert [target.archive_order for target in service.list_targets()] == [1, 2]
    assert service.disable("one").archive_order == 1
    assert "archive_order: 1" in path.read_text(encoding="utf-8")

    with pytest.raises(InvalidWatchlistError, match="every key or none"):
        add_target(service, key="three", work_key="shared")


@pytest.mark.parametrize(
    "orders",
    [
        (1, None),
        (1, 1),
        (0, 2),
        (True, 2),
        ("1", 2),
    ],
)
def test_archive_order_invalid_groups_are_rejected(
    tmp_path: Path, orders: tuple[object, object]
) -> None:
    path = tmp_path / "watchlist.yaml"
    entries = []
    for index, order in enumerate(orders, start=1):
        item = (
            f"  - key: k{index}\n"
            "    work_key: shared\n"
            "    site: site\n"
            f"    url: https://example.invalid/{index}\n"
            "    label: Label\n"
        )
        if order is not None:
            rendered = (
                str(order).lower() if isinstance(order, bool)
                else f"'{order}'" if isinstance(order, str)
                else str(order)
            )
            item += f"    archive_order: {rendered}\n"
        entries.append(item)
    path.write_text("targets:\n" + "".join(entries), encoding="utf-8")
    with pytest.raises(InvalidWatchlistError, match="archive_order"):
        WatchlistService(path).list_targets()


def test_watchlist_mutations_preserve_unrelated_comments(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    original = (
        "# keep document comment\n"
        "targets:\n"
        "  # keep target comment\n"
        "  - key: one # inline target comment\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    enabled: true # retain enabled note\n"
        "    label: One\n"
        "# keep trailing comment\n"
    )
    path.write_text(original, encoding="utf-8")
    service = WatchlistService(path)

    service.disable("one")

    after = path.read_text(encoding="utf-8")
    assert "# keep document comment" in after
    assert "# keep target comment" in after
    assert "# inline target comment" in after
    assert "# retain enabled note" in after
    assert "# keep trailing comment" in after
    assert "enabled: false" in after

    with pytest.raises(WatchlistError, match="edit the target mapping directly"):
        add_target(service, key="two", work_key="work-two", label="Two")
    assert path.read_text(encoding="utf-8") == after


@pytest.mark.parametrize("removed_key", ["one", "two", "three"])
def test_remove_first_middle_or_last_target_preserves_other_targets(
    tmp_path: Path, removed_key: str
) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    label: One\n"
        "  - key: two\n"
        "    work_key: work-two\n"
        "    site: bookwalker\n"
        "    url: https://example.invalid/two\n"
        "    label: Two\n"
        "  - key: three\n"
        "    work_key: work-three\n"
        "    site: magapoke\n"
        "    url: https://example.invalid/three\n"
        "    label: Three\n"
        "",
        encoding="utf-8",
    )
    service = WatchlistService(path)

    service.remove(removed_key)

    assert [target.key for target in service.list_targets()] == [
        key for key in ("one", "two", "three") if key != removed_key
    ]


def test_remove_from_comment_bearing_watchlist_fails_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "watchlist.yaml"
    original = (
        "# keep me\n"
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        "    label: One\n"
    )
    path.write_text(original, encoding="utf-8")
    with pytest.raises(WatchlistError, match="edit the target mapping directly"):
        WatchlistService(path).remove("one")
    assert path.read_text(encoding="utf-8") == original


def test_adding_all_archive_orders_roundtrips_for_commentless_watchlist(
    tmp_path: Path,
) -> None:
    path = tmp_path / "watchlist.yaml"
    path.write_text(
        "targets:\n"
        "  - key: one\n"
        "    work_key: shared\n"
        "    site: zebrak\n"
        "    url: https://example.invalid/one\n"
        "    label: One\n"
        "  - key: two\n"
        "    work_key: shared\n"
        "    site: bookwalker\n"
        "    url: https://example.invalid/two\n"
        "    label: Two\n",
        encoding="utf-8",
    )
    service = WatchlistService(path)
    previous = service.list_targets()
    updated = [
        replace(previous[0], archive_order=10),
        replace(previous[1], archive_order=20),
    ]

    service._write(updated, previous=previous)

    assert [target.archive_order for target in service.list_targets()] == [10, 20]
    written = path.read_text(encoding="utf-8")
    assert written.count("archive_order:") == 2


def test_adding_archive_order_to_commented_watchlist_fails_without_writing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "watchlist.yaml"
    original = (
        "# preserve me\n"
        "targets:\n"
        "  - key: one\n"
        "    work_key: shared\n"
        "    site: zebrak\n"
        "    url: https://example.invalid/one\n"
        "    label: One\n"
        "  - key: two\n"
        "    work_key: shared\n"
        "    site: bookwalker\n"
        "    url: https://example.invalid/two\n"
        "    label: Two\n"
    )
    path.write_text(original, encoding="utf-8")
    service = WatchlistService(path)
    previous = service.list_targets()
    updated = [
        replace(previous[0], archive_order=10),
        replace(previous[1], archive_order=20),
    ]
    with pytest.raises(WatchlistError, match="edit the target mapping directly"):
        service._write(updated, previous=previous)
    assert path.read_text(encoding="utf-8") == original


def test_multiline_quoted_hash_blocks_structural_rewrite_without_writing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "watchlist.yaml"
    original = (
        "targets:\n"
        "  - key: one\n"
        "    work_key: work-one\n"
        "    site: mangaone\n"
        "    url: https://example.invalid/one\n"
        '    label: "line one\n'
        "      line two # preserve this text\"\n"
    )
    path.write_text(original, encoding="utf-8")
    service = WatchlistService(path)

    assert service.get("one").label == "line one line two # preserve this text"
    with pytest.raises(WatchlistError, match="edit the target mapping directly"):
        add_target(service, key="two", work_key="work-two", label="Two")
    assert path.read_text(encoding="utf-8") == original


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
