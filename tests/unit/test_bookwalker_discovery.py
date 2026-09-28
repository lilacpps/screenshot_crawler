from __future__ import annotations

import pytest

from screenshot_crawler.discovery import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
    DiscoveryIncompleteError,
    DiscoverySourceSnapshot,
    IncrementalStopDecision,
)
from screenshot_crawler.site_adapters.bookwalker.discovery import (
    BookWalkerAccountState,
    BookWalkerDiscoveryAdapter,
    BookWalkerListedProduct,
    classify_bookwalker_account_state,
    clean_bookwalker_author,
    find_bookwalker_first_volume_candidates,
    is_bookwalker_special_title,
    map_bookwalker_access_mode,
    normalize_bookwalker_series_title,
    parse_bookwalker_order,
    parse_bookwalker_product_url,
    parse_bookwalker_series_url,
    resolve_bookwalker_order,
)
from screenshot_crawler.watchlist import WatchlistTarget


def test_bookwalker_series_url_parser_is_strict() -> None:
    assert parse_bookwalker_series_url(
        "https://bookwalker.jp/series/123/list/?from=watchlist"
    ).series_id == "123"
    assert parse_bookwalker_series_url("https://www.bookwalker.jp/series/123/list/")
    assert parse_bookwalker_series_url("http://bookwalker.jp/series/123/list/") is None
    assert parse_bookwalker_series_url("https://bookwalker.jp/series/abc/list/") is None
    assert parse_bookwalker_series_url("https://bookwalker.jp/de123/") is None


def test_bookwalker_product_identity_uses_de_uuid() -> None:
    product = parse_bookwalker_product_url(
        "https://bookwalker.jp/de6DE7534D-7022-481D-B2D3-05F03F384454/?x=1"
    )
    assert product is not None
    assert product.external_id == "6de7534d-7022-481d-b2d3-05f03f384454"
    assert parse_bookwalker_product_url("https://bookwalker.jp/viewer/abc") is None


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({"login_cta": True}, BookWalkerAccountState.LOGGED_OUT),
        ({"password_input": True}, BookWalkerAccountState.LOGGED_OUT),
        ({"auth_challenge": True}, BookWalkerAccountState.AMBIGUOUS),
        ({"member_link": True}, BookWalkerAccountState.READY),
        ({}, BookWalkerAccountState.READY),
    ],
)
def test_bookwalker_account_state_requires_explicit_account_evidence(
    metadata: dict[str, object],
    expected: BookWalkerAccountState,
) -> None:
    assert classify_bookwalker_account_state(metadata) is expected


@pytest.mark.parametrize(
    "title",
    [
        "【購入特典】作品",
        "【特典】作品",
        "〖購入特典〗作品",
        "〖特典〗作品",
    ],
)
def test_bookwalker_special_title_prefixes(title: str) -> None:
    assert is_bookwalker_special_title(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "作品名 #16",
        "作品名 特典について #16",
    ],
)
def test_bookwalker_special_title_requires_prefix(title: str) -> None:
    assert is_bookwalker_special_title(title) is False


@pytest.mark.parametrize(
    ("controls", "expected"),
    [
        ([{"text": "試し読み", "action": "trial_reading", "href": ""}], "paid"),
        ([{"text": "10分まる読み", "action": "subscription_reading", "href": ""}], "quota"),
        ([{"text": "読み放題で読む", "action": "subscription_reading", "href": ""}], "unknown"),
        ([{"text": "", "action": None, "href": "https://viewer.bookwalker.jp/viewer"}], "unknown"),
        ([], "unknown"),
        ([{"text": "読む", "action": "reading", "href": ""}], "owned"),
        ([{"text": "読む", "action": "read_purchased", "href": ""}], "owned"),
        (
            [
                {"text": "試し読み", "action": "trial_reading", "href": ""},
                {"text": "読む", "action": "reading", "href": ""},
            ],
            "owned",
        ),
        (
            [
                {"text": "試し読み", "action": "trial_reading", "href": ""},
                {"text": "10分まる読み", "action": "read_maruyomi", "href": ""},
            ],
            "quota",
        ),
    ],
)
def test_bookwalker_access_mode_uses_reader_classifier(
    controls: list[dict[str, object]],
    expected: str,
) -> None:
    assert map_bookwalker_access_mode(controls) == expected


def test_bookwalker_order_keeps_special_products_unparsed() -> None:
    assert parse_bookwalker_order("作品名4") == ("4", "第04巻")
    assert parse_bookwalker_order("作品名 #16 サブタイトル") == ("16", "第16巻")
    assert parse_bookwalker_order("作品名 第16巻") == ("16", "第16巻")
    assert parse_bookwalker_order("作品名 16巻") == ("16", "第16巻")
    assert parse_bookwalker_order(
        "【購入特典】『作品名 #16 サブタイトル』BOOK☆WALKER限定",
        special=True,
    ) == (
        None,
        "『作品名 #16 サブタイトル』BOOK☆WALKER限定",
    )
    assert parse_bookwalker_order("作品名 番外編") == (None, "作品名 番外編")


def _listed_product(
    number: int,
    title: str,
    *,
    special: bool = False,
) -> BookWalkerListedProduct:
    external_id = f"00000000-0000-0000-0000-{number:012d}"
    return BookWalkerListedProduct(
        external_id=external_id,
        url=f"https://bookwalker.jp/de{external_id}/",
        title=title,
        special=special,
    )


def test_bookwalker_first_volume_inference_requires_series_evidence_and_exact_candidate() -> None:
    products = [
        _listed_product(1, "作品名"),
        _listed_product(2, "作品名2"),
        _listed_product(3, "作品名3"),
    ]

    series_heading = "『作品名（電撃文庫）(ライトノベル)』の電子書籍一覧"
    assert normalize_bookwalker_series_title(series_heading) == "作品名"
    candidates = find_bookwalker_first_volume_candidates(products, series_heading)
    assert candidates == frozenset({"00000000-0000-0000-0000-000000000001"})
    assert resolve_bookwalker_order(
        "作品名",
        first_volume_candidate="00000000-0000-0000-0000-000000000001" in candidates,
    ) == ("1", parse_bookwalker_order("作品名1")[1])
    assert resolve_bookwalker_order("作品名", first_volume_candidate=False) == (
        None,
        "作品名",
    )


@pytest.mark.parametrize(
    ("products", "series_title", "expected_candidates"),
    [
        ([_listed_product(1, "作品名")], "作品名", set()),
        (
            [
                _listed_product(1, "作品名"),
                _listed_product(2, "作品名2"),
                _listed_product(3, "番外編", special=True),
            ],
            "作品名",
            {"00000000-0000-0000-0000-000000000001"},
        ),
        (
            [
                _listed_product(1, "作品名"),
                _listed_product(2, "作品名"),
                _listed_product(3, "作品名2"),
            ],
            "作品名",
            set(),
        ),
        (
            [
                _listed_product(1, "作品名"),
                _listed_product(2, "作品名2"),
            ],
            "独自label",
            set(),
        ),
    ],
)
def test_bookwalker_first_volume_inference_is_conservative(
    products: list[BookWalkerListedProduct],
    series_title: str,
    expected_candidates: set[str],
) -> None:
    assert find_bookwalker_first_volume_candidates(products, series_title) == frozenset(
        expected_candidates
    )


def test_bookwalker_first_volume_inference_supports_hash_numbered_later_volumes() -> None:
    products = [
        _listed_product(1, "作品名"),
        _listed_product(2, "作品名 #2"),
        _listed_product(3, "作品名 #3"),
    ]

    assert find_bookwalker_first_volume_candidates(products, "作品名") == frozenset(
        {"00000000-0000-0000-0000-000000000001"}
    )


@pytest.mark.parametrize(
    ("raw_author", "expected"),
    [
        ("著者西 条陽 イラストRe岳", "西 条陽"),
        ("著者: 西 条陽 原作Re岳", "西 条陽"),
        ("西 条陽", "西 条陽"),
        ("", None),
        (None, None),
    ],
)
def test_bookwalker_author_keeps_author_role_only(
    raw_author: object,
    expected: str | None,
) -> None:
    assert clean_bookwalker_author(raw_author) == expected


def test_bookwalker_hooks_preserve_scope_and_stable_access() -> None:
    adapter = BookWalkerDiscoveryAdapter()
    target = WatchlistTarget(
        key="series-one",
        work_key="series-work",
        site="bookwalker",
        url="https://bookwalker.jp/series/123/list/",
        label="表示用シリーズ名",
    )
    previous = DiscoverySourceSnapshot(
        external_id="product-one",
        discovery_key="series-one",
        access_mode="quota",
        available=True,
    )
    assert adapter.reconcile_access_mode("paid", previous, target) == "quota"
    minimal_record = DiscoveredRecord(
        item=DiscoveredItem(),
        source=DiscoveredSource(
            external_id="product-one",
            url="https://bookwalker.jp/deproduct-one/",
        ),
    )
    assert adapter.incremental_stop_decision(minimal_record, previous, target) is (
        IncrementalStopDecision.STOP
    )
    with pytest.raises(DiscoveryIncompleteError):
        adapter.reconcile_access_mode(
            "paid",
            DiscoverySourceSnapshot(
                external_id="product-one",
                discovery_key="other-series",
                access_mode="quota",
                available=True,
            ),
            target,
        )
