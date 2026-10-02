import textwrap
from types import SimpleNamespace

import pytest

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.comicdays import discovery as discovery_module
from screenshot_crawler.site_adapters.comicdays.discovery import (
    canonical_comicdays_episode_url,
    parse_atom_entries,
    parse_comicdays_episode_url,
)
from screenshot_crawler.watchlist.models import WatchlistTarget


def _feed(link: str = "https://comic-days.com/episode/2", *, feed_id: str | None = None) -> bytes:
    identity = f"<id>{feed_id}</id>" if feed_id else ""
    return textwrap.dedent(f"""\
      <feed xmlns="http://www.w3.org/2005/Atom">{identity}<entry>
        <id>comicdays:episode:2</id><title>第2話</title><updated>2026-01-01T00:00:00Z</updated>
        <link rel="enclosure" href="https://cdn.comic-days.com/thumb/2.jpg"/><link href="{link}"/>
      </entry></feed>
    """).encode()


def test_comicdays_url_parser_is_canonical_and_strict() -> None:
    assert parse_comicdays_episode_url("https://comic-days.com/episode/12") == "12"
    assert parse_comicdays_episode_url("https://www.comic-days.com/episode/12") == "12"
    assert parse_comicdays_episode_url("https://comic-days.com/episode/12?free_only=1") is None
    assert parse_comicdays_episode_url("https://example.test/episode/12") is None
    assert canonical_comicdays_episode_url("https://www.comic-days.com/episode/12") == "https://comic-days.com/episode/12"


def test_atom_uses_matching_episode_link_and_ignores_thumbnail() -> None:
    entries = parse_atom_entries(_feed(), expected_series_id="42")
    assert entries == [{"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話", "updated": "2026-01-01T00:00:00Z"}]


def test_atom_rejects_conflicting_episode_identity() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        parse_atom_entries(_feed("https://comic-days.com/episode/9"), expected_series_id="42")


def test_atom_requires_exact_series_identity_when_feed_provides_one() -> None:
    with pytest.raises(DiscoveryIncompleteError):
        parse_atom_entries(_feed(feed_id="https://comic-days.com/atom/series/420"), expected_series_id="42")


class _FakeLocator:
    async def count(self) -> int:
        return 1

    async def inner_text(self, **_kwargs: object) -> str:
        return "Synthetic Work"


class _FakePage:
    url = "https://comic-days.com/episode/1"
    request = SimpleNamespace()

    async def goto(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def evaluate(self, _script: str) -> list[str]:
        return ["42"]

    def locator(self, _selector: str) -> _FakeLocator:
        return _FakeLocator()


@pytest.mark.asyncio
async def test_discovery_buffers_until_full_free_and_total_contracts_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    full = [
        {"episode_id": "2", "url": "https://comic-days.com/episode/2", "title": "第2話"},
        {"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"},
    ]
    free = [full[1]]
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return free if free_only else full
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    rows = [row async for row in discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full")]
    assert [row.source.external_id for row in rows] == ["2", "1"]
    assert [row.source.access_mode for row in rows] == ["unknown", "free"]


@pytest.mark.asyncio
async def test_discovery_total_mismatch_yields_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    async def atom(_page: object, _series: str, *, free_only: bool) -> list[dict[str, str | None]]:
        return [{"episode_id": "1", "url": "https://comic-days.com/episode/1", "title": "第1話"}]
    async def total(_page: object, _series: str, _episode: str) -> int:
        return 2
    monkeypatch.setattr(discovery_module, "fetch_comicdays_atom", atom)
    monkeypatch.setattr(discovery_module, "fetch_comicdays_listing_total", total)
    target = WatchlistTarget("k", "w", "comicdays", "https://comic-days.com/episode/1", "x")
    iterator = discovery_module.ComicDaysDiscoveryAdapter().iter_records(_FakePage(), target, "full")
    with pytest.raises(DiscoveryIncompleteError):
        await anext(iterator)
