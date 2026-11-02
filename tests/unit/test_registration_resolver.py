from dataclasses import replace

import pytest

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver, split_inputs

URLS = {
    "bookwalker": "https://bookwalker.jp/series/123/list/",
    "comicdays": "https://comic-days.com/episode/123",
    "comicfuz": "https://comic-fuz.com/manga/123",
    "hanayume": "https://hanayume.com/episodes/abcdef1234567",
    "jumpplus": "https://shonenjumpplus.com/episode/123",
    "kadocomi": "https://comic-walker.com/detail/KC_004915_S",
    "magapoke": "https://pocket.shonenmagazine.com/title/01539/episode/123",
    "mangaone": "https://manga-one.com/manga/123/chapter/456",
    "piccoma": "https://piccoma.com/web/viewer/123/456",
    "younganimal": "https://younganimal.com/series/abcdef1234567",
    "zeblack": "https://zebrack-comic.shueisha.co.jp/title/123/chapter/list",
}


@pytest.fixture
def resolver():
    return UrlResolver(_discovery_registry())


@pytest.mark.parametrize("site,url", URLS.items())
def test_current_entries_are_read_only_and_title_unknown(resolver, site, url, tmp_path):
    before = tuple(tmp_path.iterdir())
    result = resolver.resolve(url)
    assert result.site == site
    assert result.status == "valid", result
    assert result.discovery_url == url
    assert result.title is None and result.title_status == "unknown"
    assert result.identity_status in ("verified", "unknown")
    assert before == tuple(tmp_path.iterdir())


def test_registry_coverage(resolver):
    assert set(resolver.registry.sites()) == set(URLS)


@pytest.mark.parametrize("change", [
    lambda u: u.replace("https:", "http:"),
    lambda u: u.replace("://", "://user@"),
    lambda u: u.replace(".com/", ".com.evil.test/"),
    lambda u: u + "#top", lambda u: u + "#", lambda u: u + "?",
    lambda u: u + "?redirect=https://evil.test", lambda u: u + ";x",
    lambda u: u + "\n", lambda u: u.replace("/123", "/%31%32%33"),
    lambda u: u.replace(".com/", ".com:80/"), lambda u: u + "\\",
])
@pytest.mark.parametrize("url", URLS.values())
def test_unsafe_variants_are_blocked(resolver, url, change):
    altered = change(url)
    if altered == url:
        return
    assert resolver.resolve(altered).status == "blocked"


@pytest.mark.parametrize("url", [
    "https://127.0.0.1/", "https://localhost/", "https://10.0.0.1/",
    "https://comic-walker.com:bad/detail/KC_004915_S",
    "https://comic-walker.com/detail/KC_004915_S/episodes/KC_0116050000100001_E",
    "https://piccoma.com/web/product/123/episodes",
    "https://bookwalker.jp/de123/", "https://shonenjumpplus.com/series/123",
])
def test_unsupported_not_rescued(resolver, url):
    assert resolver.resolve(url).status == "blocked"


@pytest.mark.parametrize("query", ["", "?co=true", "?episodeType=first",
    "?co=true&episodeType=first", "?episodeType=first&co=true"])
def test_kadocomi_pilot_same_work_conversion(resolver, query):
    result = resolver.resolve(
        "https://comic-walker.com/detail/KC_004915_S/episodes/KC_0049150000100001_E" + query)
    assert result.status == "converted"
    assert result.discovery_url == URLS["kadocomi"]
    assert result.site_work_identity == "kadocomi-work:KC_004915_S"
    assert result.title is None


@pytest.mark.parametrize("url", [
    "https://zebrack-comic.shueisha.co.jp/title/3957/chapter/464465/viewer",
    "https://zebrack-comic.shueisha.co.jp/title/003957/chapter/00464465/viewer",
])
def test_zeblack_viewer_converts_without_opening_reader(resolver, url):
    result = resolver.resolve(url)
    title = url.split("/")[4]
    assert result.status == "converted"
    assert result.discovery_url == f"https://zebrack-comic.shueisha.co.jp/title/{title}/chapter/list"
    assert result.site_work_identity == "zeblack-title:" + title
    assert result.title is None


@pytest.mark.parametrize("suffix", ["?x=1", "#top", "/", ";x"])
def test_zeblack_viewer_conversion_does_not_relax_url_safety(resolver, suffix):
    assert resolver.resolve("https://zebrack-comic.shueisha.co.jp/title/3957/chapter/464465/viewer" + suffix).status == "blocked"


async def test_observation_rejects_tampered_resolution(resolver):
    result = resolver.resolve(URLS["kadocomi"])
    assert (await resolver.observe(None, replace(result, discovery_url="https://evil.test"))).status == "blocked"


def test_input_limits_and_order():
    assert split_inputs(" A\n\nB\nA\n") == ((1, "A"), (3, "B"))
    with pytest.raises(ValueError):
        split_inputs("x\n" * 101)
    with pytest.raises(ValueError):
        split_inputs("x" * 4097)
