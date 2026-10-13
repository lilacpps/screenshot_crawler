from __future__ import annotations

import pytest

from screenshot_crawler.cli import _batch_adapter_registry, _discovery_registry, _registry
from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicfuz import ComicFuzAdapter, ComicFuzDiscoveryAdapter
from screenshot_crawler.site_adapters.comicfuz.discovery import (
    ComicFuzWorkParts,
    _flatten_chapters,
    parse_comicfuz_episode_url,
    parse_comicfuz_work_url,
)


def test_comicfuz_work_url_accepts_only_canonical_work_and_observed_hint() -> None:
    assert parse_comicfuz_work_url(
        "https://comic-fuz.com/manga/1970?position=thumbnail"
    ) == ComicFuzWorkParts(work_id="1970")
    assert parse_comicfuz_work_url("https://comic-fuz.com/manga/1970") == (
        ComicFuzWorkParts(work_id="1970")
    )

    for url in (
        "http://comic-fuz.com/manga/1970",
        "https://www.comic-fuz.com/manga/1970",
        "https://comic-fuz.com.evil.example/manga/1970",
        "https://comic-fuz.com/manga/1970?other=1",
        "https://comic-fuz.com/manga/1970?position=thumbnail&position=thumbnail",
        "https://user@comic-fuz.com/manga/1970",
        "https://comic-fuz.com:443/manga/1970",
        "https://comic-fuz.com/manga/1970/",
        "https://comic-fuz.com/manga/not-a-number",
        "https://comic-fuz.com/manga/1970#chapter",
    ):
        assert parse_comicfuz_work_url(url) is None


def test_comicfuz_discovery_adapter_is_registered() -> None:
    assert isinstance(_discovery_registry().create("comicfuz"), ComicFuzDiscoveryAdapter)


def test_comicfuz_viewer_is_registered_for_manual_crawl_and_batch() -> None:
    assert isinstance(_registry().create("comicfuz"), ComicFuzAdapter)
    batch_adapter = _batch_adapter_registry(
        {"COMICFUZ_WORK_URL": "https://comic-fuz.com/manga/1970?position=thumbnail"}
    ).create("comicfuz")
    assert isinstance(batch_adapter, ComicFuzAdapter)


def test_comicfuz_episode_url_requires_observed_canonical_reader_route() -> None:
    assert parse_comicfuz_episode_url("https://comic-fuz.com/manga/viewer/80641") == "80641"
    for url in (
        "http://comic-fuz.com/manga/viewer/80641",
        "https://www.comic-fuz.com/manga/viewer/80641",
        "https://comic-fuz.com/manga/viewer/80641?position=2",
        "https://comic-fuz.com/manga/viewer/not-an-id",
        "https://comic-fuz.com/manga/1970/viewer/80641",
    ):
        assert parse_comicfuz_episode_url(url) is None


def test_comicfuz_hydration_flattening_uses_only_ids_and_labels() -> None:
    assert _flatten_chapters(
        {
            "chapters": [
                {
                    "chapters": [
                        {"chapterId": 2, "chapterMainName": " 第2話 ", "pointConsumption": 99}
                    ]
                },
                {"chapters": [{"chapterId": "1", "chapterMainName": "第1話"}]},
            ]
        }
    ) == [("2", "第2話"), ("1", "第1話")]


@pytest.mark.parametrize(
    "page_props",
    [
        {},
        {"chapters": []},
        {"chapters": [{"chapters": []}]},
        {"chapters": [{"chapters": [{"chapterId": True, "chapterMainName": "第1話"}]}]},
        {"chapters": [{"chapters": [{"chapterId": 1, "chapterMainName": " "}]}]},
        {
            "chapters": [
                {"chapters": [{"chapterId": 1, "chapterMainName": "第1話"}]},
                {"chapters": [{"chapterId": "1", "chapterMainName": "第1話(別版)"}]},
            ]
        },
    ],
)
def test_comicfuz_malformed_or_duplicate_hydration_fails_closed(page_props) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _flatten_chapters(page_props)
