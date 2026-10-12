from __future__ import annotations

from datetime import datetime

import pytest

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.kadocomi.discovery import (
    NO_DEADLINE_VERIFIED_WORK_ID,
    _canonical_work_title,
    _parse_listing_rows,
    _read_expand_button,
    canonical_kadocomi_episode_url,
    canonical_kadocomi_work_url,
    classify_kadocomi_access,
    parse_kadocomi_deadline,
    parse_kadocomi_episode_url,
    parse_kadocomi_work_url,
)

BASE = "https://comic-walker.com"
WORK_ID = "KC_004915_S"
OBSERVED_AT = datetime(2026, 10, 12, 12, tzinfo=JST)


def _episode_id(number: int) -> str:
    return f"KC_004915{number:010d}_E"


def _raw_row(number: int, *, href: str | None = None, label: str | None = None, row_text: str | None = None):
    episode_id = _episode_id(number)
    title = label or f"\u7B2C{number}\u8A71"
    return {
        "href": href
        or f"/detail/{WORK_ID}/episodes/{episode_id}?co=true&episodeType=first",
        "label": title,
        "rowText": row_text or f"2026/10/07 2026\u5E7410\u670807\u65E5 {title}",
        "rowLinkCount": 1,
    }


def test_kadocomi_work_and_episode_urls_accept_only_observed_shapes() -> None:
    work_url = f"{BASE}/detail/{WORK_ID}?episodeType=first"
    assert parse_kadocomi_work_url(work_url).work_id == WORK_ID
    assert canonical_kadocomi_work_url(work_url) == f"{BASE}/detail/{WORK_ID}"

    episode_id = _episode_id(4)
    observed = (
        f"{BASE}/detail/{WORK_ID}/episodes/{episode_id}"
        "?co=true&episodeType=first"
    )
    assert parse_kadocomi_episode_url(observed).episode_id == episode_id
    assert canonical_kadocomi_episode_url(observed) == (
        f"{BASE}/detail/{WORK_ID}/episodes/{episode_id}"
    )

    for unsupported in (
        f"http://comic-walker.com/detail/{WORK_ID}",
        f"https://www.comic-walker.com/detail/{WORK_ID}",
        f"{BASE}/detail/{WORK_ID}?unknown=1",
        f"{BASE}/detail/{WORK_ID}?co=true",
        f"{BASE}/detail/{WORK_ID}/episodes/{episode_id}?co=false",
        f"{BASE}/detail/{WORK_ID}/episodes/{episode_id}?co=true&other=1",
        f"https://comic-walker.com.evil.example/detail/{WORK_ID}",
        f"{BASE}/detail/KC_000000_S/episodes/{episode_id}",
        f"{BASE}/detail/{WORK_ID}/episodes/not-an-id",
    ):
        assert parse_kadocomi_work_url(unsupported) is None
        assert parse_kadocomi_episode_url(unsupported) is None


def test_kadocomi_deadline_requires_exact_label_and_valid_calendar_time() -> None:
    row_text = (
        "2026/10/07 2026\u5E7410\u670807\u65E5 \u7B2C4\u8A71\u305D\u306E1 "
        "\u914D\u4FE1\u671F\u9650\uff1a2099/10/14 11:00 "
        "2099\u5E7410\u670814\u65E5 11\u664200\u5206"
    )
    assert parse_kadocomi_deadline(row_text) == datetime(2099, 10, 14, 11, tzinfo=JST)
    assert parse_kadocomi_deadline("2026/10/07 \u7B2C1\u8A71") is None
    with pytest.raises(ValueError, match="unknown format"):
        parse_kadocomi_deadline("\u914D\u4FE1\u671F\u9650: soon")
    with pytest.raises(ValueError, match="invalid"):
        parse_kadocomi_deadline("\u914D\u4FE1\u671F\u9650:2099/02/30 11:00")
    with pytest.raises(ValueError, match="multiple"):
        parse_kadocomi_deadline(
            "\u914D\u4FE1\u671F\u9650:2099/10/14 11:00 "
            "\u914D\u4FE1\u671F\u9650:2099/10/15 11:00"
        )


def test_kadocomi_public_rows_classify_explicit_deadlines_and_observed_no_deadline() -> None:
    future = classify_kadocomi_access(
        "\u914D\u4FE1\u671F\u9650:2099/10/14 11:00",
        observed_at=OBSERVED_AT,
    )
    assert future == ("free", datetime(2099, 10, 14, 11, tzinfo=JST))
    assert classify_kadocomi_access(
        "2026/10/07 \u7B2C1\u8A71",
        observed_at=OBSERVED_AT,
        work_id=NO_DEADLINE_VERIFIED_WORK_ID,
    ) == ("free", None)
    assert classify_kadocomi_access(
        "2026/10/07 \u7B2C1\u8A71", observed_at=OBSERVED_AT, work_id="KC_000001_S"
    ) == ("unknown", None)
    assert classify_kadocomi_access(
        "\u914D\u4FE1\u671F\u9650:2026/10/01 11:00",
        observed_at=OBSERVED_AT,
    ) == ("unknown", datetime(2026, 10, 1, 11, tzinfo=JST))
    with pytest.raises(ValueError, match="access gate"):
        classify_kadocomi_access(
            "\u8CFC\u5165\u3057\u3066\u8AAD\u3080", observed_at=OBSERVED_AT
        )


def test_kadocomi_rows_keep_episode_title_and_bind_work_identity() -> None:
    title = "\u7B2C4\u8A71\u305D\u306E1"
    raw = _raw_row(
        4,
        label=title,
        row_text=(
            "2026/10/07 2026\u5E7410\u670807\u65E5 "
            f"{title} \u914D\u4FE1\u671F\u9650\uff1a2099/10/14 11:00 "
            "2099\u5E7410\u670814\u65E5 11\u664200\u5206"
        ),
    )
    rows = _parse_listing_rows(
        [raw],
        work_id=WORK_ID,
        base_url=f"{BASE}/detail/{WORK_ID}",
        observed_at=OBSERVED_AT,
    )
    assert rows[0].identity.episode_id == _episode_id(4)
    assert rows[0].external_id == f"{WORK_ID}:{_episode_id(4)}"
    assert rows[0].label == title
    assert rows[0].access_mode == "free"
    assert rows[0].deadline == datetime(2099, 10, 14, 11, tzinfo=JST)


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [_raw_row(1), _raw_row(1)],
        [_raw_row(1, href=f"/detail/KC_000000_S/episodes/{_episode_id(1)}")],
        [{**_raw_row(1), "rowLinkCount": 2}],
        [{**_raw_row(1), "label": " "}],
        [{**_raw_row(1), "rowText": "\u914D\u4FE1\u671F\u9650: invalid"}],
    ],
)
def test_kadocomi_malformed_or_ambiguous_rows_fail_closed(rows) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        _parse_listing_rows(
            rows,
            work_id=WORK_ID,
            base_url=f"{BASE}/detail/{WORK_ID}",
            observed_at=OBSERVED_AT,
        )


def test_kadocomi_work_title_comes_from_observed_detail_og_title() -> None:
    actual_og_title = "夫婦以上、恋人未満。｜カドコミ (コミックウォーカー)"
    assert _canonical_work_title(actual_og_title) == "夫婦以上、恋人未満。"
    assert _canonical_work_title(
        "Work｜カドコミ (コミックウォーカー)"
    ) == "Work"
    with pytest.raises(DiscoveryIncompleteError, match="title"):
        _canonical_work_title("Work｜カドコミ (コミックォーカー)")
    with pytest.raises(DiscoveryIncompleteError, match="title"):
        _canonical_work_title("\u7B2C1\u8A71 Work")


def test_kadocomi_expansion_label_requires_one_supported_total() -> None:
    assert _read_expand_button(["\u5168" + "53" + "\u8A71\u3092\u8868\u793A"]) == (
        "\u5168" + "53" + "\u8A71\u3092\u8868\u793A",
        53,
    )
    for labels in (
        [],
        ["More"],
        ["\u5168" + "53" + "\u8A71\u3092\u8868\u793A", "\u5168" + "54" + "\u8A71\u3092\u8868\u793A"],
        ["\u5168" + "0" + "\u8A71\u3092\u8868\u793A"],
    ):
        with pytest.raises(DiscoveryIncompleteError):
            _read_expand_button(labels)
