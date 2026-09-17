from pathlib import Path

import pytest

from screenshot_crawler.watchlist import (
    DuplicateWatchlistKeyError,
    InvalidWatchlistError,
    WatchlistService,
    WatchlistTargetNotFoundError,
)


def test_new_watchlist_is_empty_and_adds_optional_label(tmp_path: Path) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")

    assert service.list_targets() == []
    added = service.add(key="one", site="mangaone", url="https://example.invalid/one")

    assert added.enabled is True
    assert added.label is None
    assert service.list_targets() == [added]
    assert "targets:" in (tmp_path / "watchlist.yaml").read_text(encoding="utf-8")


def test_watchlist_crud_and_duplicate_key(tmp_path: Path) -> None:
    service = WatchlistService(tmp_path / "watchlist.yaml")
    service.add(key="one", site="bookwalker", url="https://example.invalid/one", label="作品A")

    with pytest.raises(DuplicateWatchlistKeyError):
        service.add(key="one", site="bookwalker", url="https://example.invalid/two")

    disabled = service.disable("one")
    assert disabled.enabled is False
    assert service.get("one").enabled is False
    assert service.enable("one").enabled is True
    assert service.remove("one").label == "作品A"
    assert service.list_targets() == []

    with pytest.raises(WatchlistTargetNotFoundError):
        service.remove("missing")


@pytest.mark.parametrize(
    "content",
    [
        "targets: [",
        "{}",
        "targets: {}",
        "targets:\n  - site: mangaone\n    url: https://example.invalid/one\n",
        "targets:\n  - key: one\n    site: mangaone\n    url: https://example.invalid/one\n    enabled: 1\n",
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
        "  - {key: one, site: mangaone, url: https://example.invalid/one}\n"
        "  - {key: one, site: mangaone, url: https://example.invalid/two}\n",
        encoding="utf-8",
    )

    with pytest.raises(DuplicateWatchlistKeyError):
        WatchlistService(path).list_targets()
