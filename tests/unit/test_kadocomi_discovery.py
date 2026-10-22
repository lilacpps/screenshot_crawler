from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from uuid import UUID

import pytest

from screenshot_crawler.catalog.service import JST
from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryIncompleteError,
)
from screenshot_crawler.site_adapters.kadocomi.discovery import (
    KadocomiDiscoveryAdapter,
    _canonical_work_title,
    _native_inactive_runs,
    _parse_listing_rows,
    _parse_native_work_listing,
    _read_expand_button,
    canonical_kadocomi_episode_url,
    canonical_kadocomi_work_url,
    classify_kadocomi_access,
    parse_kadocomi_deadline,
    parse_kadocomi_episode_url,
    parse_kadocomi_work_url,
)
from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget

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


@pytest.mark.parametrize("work_id", [None, WORK_ID, "KC_011605_S", "KC_000001_S"])
def test_kadocomi_public_rows_classify_explicit_deadlines_and_no_deadline(work_id) -> None:
    future = classify_kadocomi_access(
        "\u914D\u4FE1\u671F\u9650:2099/10/14 11:00",
        observed_at=OBSERVED_AT,
    )
    assert future == ("free", datetime(2099, 10, 14, 11, tzinfo=JST))
    assert classify_kadocomi_access(
        "2026/10/07 \u7B2C1\u8A71",
        observed_at=OBSERVED_AT,
        work_id=work_id,
    ) == ("free", None)
    assert classify_kadocomi_access(
        "\u914D\u4FE1\u671F\u9650:2026/10/01 11:00",
        observed_at=OBSERVED_AT,
    ) == ("unknown", datetime(2026, 10, 1, 11, tzinfo=JST))
    assert classify_kadocomi_access(
        "配信期限:2026/10/12 12:00", observed_at=OBSERVED_AT
    ) == ("unknown", OBSERVED_AT)


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
        *[
            [_raw_row(1, row_text=f"第1話 {gate}")]
            for gate in ("購入", "有料", "有料会員", "ログイン", "チケット", "コイン",
                         "ポイント", "レンタル", "アプリ")
        ],
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


def _native_entry(number: int, *, active: bool, title: str | None = None) -> dict:
    code = _episode_id(number)
    episode_type = "normal"
    return {
        "code": code,
        "id": str(UUID(int=number)),
        "title": title or f"Chapter {number}",
        "serviceId": "web",
        "type": episode_type,
        "isActive": active,
        "internal": {
            "episodeNo": number,
            "episodetype": episode_type,
            "pageCount": 12,
        },
        # Unrelated first-party fields are deliberately not part of the proof.
        "hasRead": True,
        "deliveryPeriod": {"notAfter": "ignored"},
    }


def _native_payload() -> dict:
    entries = [
        _native_entry(1, active=True),
        _native_entry(2, active=True),
        _native_entry(5, active=False),
        _native_entry(7, active=True),
        _native_entry(9, active=False),
    ]
    return {
        "props": {
            "pageProps": {
                "dehydratedState": {
                    "queries": [
                        {
                            "queryKey": [
                                "/api/contents/details/work",
                                {"workCode": WORK_ID},
                            ],
                            "state": {
                                "data": {
                                    "work": {
                                        "code": WORK_ID,
                                        "id": str(UUID(int=100)),
                                        "title": "Fixture Work",
                                    },
                                    "firstEpisodes": {
                                        "total": len(entries),
                                        "result": entries,
                                    },
                                    "latestEpisodes": {
                                        "total": len(entries),
                                        "result": list(reversed(entries)),
                                    },
                                }
                            },
                        }
                    ]
                }
            }
        }
    }


def test_native_kadocomi_history_preserves_explicit_gapped_positions_and_runs() -> None:
    listing = _parse_native_work_listing(_native_payload(), work_id=WORK_ID)

    assert listing.work_id == WORK_ID
    assert listing.work_title == "Fixture Work"
    assert [episode.episode_no for episode in listing.episodes] == [1, 2, 5, 7, 9]
    assert [episode.is_active for episode in listing.episodes] == [True, True, False, True, False]
    runs = _native_inactive_runs(listing.episodes)
    assert [
        (
            previous.title if previous else None,
            tuple(episode.title for episode in inactive),
            following.title if following else None,
        )
        for previous, inactive, following in runs
    ] == [
        ("Chapter 2", ("Chapter 5",), "Chapter 7"),
        ("Chapter 7", ("Chapter 9",), None),
    ]


def test_native_kadocomi_history_accepts_explicit_extra_episode_type() -> None:
    payload = _native_payload()
    query = payload["props"]["pageProps"]["dehydratedState"]["queries"][0]
    first = query["state"]["data"]["firstEpisodes"]["result"]
    first[2]["type"] = "extra"
    first[2]["internal"]["episodetype"] = "extra"
    query["state"]["data"]["latestEpisodes"]["result"] = list(reversed(first))

    listing = _parse_native_work_listing(payload, work_id=WORK_ID)

    assert listing.episodes[2].episode_type == "extra"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"].update(total=6),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["latestEpisodes"]["result"].reverse(),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2]["internal"].update(episodeNo=2),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2].update(serviceId="app"),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2].update(isActive=1),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2].update(id="not-a-uuid"),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"].append(deepcopy(payload["props"]["pageProps"]["dehydratedState"]["queries"][0])),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["queryKey"][1].update(workCode="KC_011605_S"),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["work"].update(code="KC_011605_S"),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2].update(code=payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][0]["code"]),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][2].update(id=payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"][0]["id"]),
        lambda payload: payload["props"]["pageProps"]["dehydratedState"]["queries"][0]["state"]["data"]["firstEpisodes"]["result"].append(_native_entry(11, active=False)),
    ],
    ids=[
        "total-mismatch",
        "latest-order",
        "duplicate-position",
        "non-web",
        "non-boolean-active",
        "bad-uuid",
        "duplicate-query",
        "query-work-mismatch",
        "work-identity-mismatch",
        "duplicate-code",
        "duplicate-uuid",
        "extra-unaccounted-row",
    ],
)
def test_native_kadocomi_history_rejects_incomplete_or_ambiguous_data(mutate) -> None:
    payload = _native_payload()
    mutate(payload)
    with pytest.raises(DiscoveryIncompleteError):
        _parse_native_work_listing(payload, work_id=WORK_ID)


@pytest.mark.parametrize(
    ("from_number", "through_number", "expected"),
    [
        (5, None, [5, 2, 1]),
        (None, 5, [9, 7, 5]),
        (7, 2, [7, 5, 2]),
        (7, 7, [7]),
    ],
    ids=["from-only", "through-only", "both-inclusive", "singleton"],
)
def test_native_kadocomi_scope_selects_latest_first_inclusive_slice(
    from_number: int | None,
    through_number: int | None,
    expected: list[int],
) -> None:
    listing = _parse_native_work_listing(_native_payload(), work_id=WORK_ID)
    records = [
        DiscoveredRecord(
            item=DiscoveredItem(order_label=episode.title),
            source=DiscoveredSource(
                external_id=f"{WORK_ID}:{episode.episode_id}",
                url=canonical_kadocomi_episode_url(
                    f"{BASE}/detail/{WORK_ID}/episodes/{episode.episode_id}"
                ),
                global_display_position=episode.episode_no,
            ),
        )
        for episode in reversed(listing.episodes)
    ]

    def boundary_url(number: int | None) -> str | None:
        if number is None:
            return None
        return canonical_kadocomi_episode_url(
            f"{BASE}/detail/{WORK_ID}/episodes/{_episode_id(number)}"
        )

    target = WatchlistTarget(
        key="native-scope",
        work_key=f"kadocomi:{WORK_ID}",
        site="kadocomi",
        url=f"{BASE}/detail/{WORK_ID}",
        label="Fixture Work",
        discovery_scope=DiscoveryScope(
            from_url=boundary_url(from_number),
            through_url=boundary_url(through_number),
        ),
        archive_order=1,
    )

    selected = KadocomiDiscoveryAdapter._select_native_scope(records, target, WORK_ID)

    assert [record.source.global_display_position for record in selected] == expected
