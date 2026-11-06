from __future__ import annotations

from typing import Any

import pytest

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.ebookjapan.discovery import (
    EbookJapanDiscoveryAdapter,
    _source_rights_match,
    parse_ebookjapan_listing,
    parse_ebookjapan_series_url,
    parse_ebookjapan_source_witness,
)
from screenshot_crawler.watchlist.models import WatchlistTarget


def _row(
    index: int,
    product_id: str,
    title: str,
    *,
    owned: bool = False,
    hidden_owned: bool = False,
    price: str | None = None,
    basket_count: int = 0,
    conflicting_badge: str | None = None,
) -> dict[str, Any]:
    badges = []
    if owned:
        badges.append({"text": "購入済み", "visible": True})
    if hidden_owned:
        badges.append({"text": "購入済み", "visible": False})
    if conflicting_badge:
        badges.append({"text": conflicting_badge, "visible": True})
    return {
        "index": index,
        "path": f"/books/134336/{product_id}/",
        "linkCount": 1,
        "title": title,
        "visible": True,
        "badges": badges,
        "visiblePrices": [price] if price else [],
        "basketCount": basket_count,
    }


def _payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    paths = [row["path"] for row in rows]
    return {
        "pageHost": "ebookjapan.yahoo.co.jp",
        "pagePath": "/books/all/134336/",
        "pageUrl": "https://ebookjapan.yahoo.co.jp/books/all/134336/",
        "canonicalCount": 1,
        "canonicalPath": "/books/all/134336/",
        "declaredTotal": len(rows),
        "oldestFirst": True,
        "seriesTitle": "Example series",
        "accountAuthenticated": True,
        "cardCount": len(rows),
        "rows": rows,
        "domPaths": paths,
        "layoutPaths": paths.copy(),
        "paginationCount": 0,
        "loadMoreCount": 0,
    }


def test_full_inventory_preserves_observed_oldest_positions_and_owned_mask() -> None:
    rows = [
        _row(0, "A000000001", "Example series", owned=True),
        _row(1, "A000000002", "Example series 2巻", price="646円（税込）", basket_count=1),
        _row(2, "A000000003", "Example series（3）", owned=True),
    ]

    all_records, owned_records = parse_ebookjapan_listing(_payload(rows), series_id="134336")
    adapter = EbookJapanDiscoveryAdapter()
    target = WatchlistTarget(
        key="example_ebookjapan",
        work_key="example",
        site="ebookjapan",
        url="https://ebookjapan.yahoo.co.jp/books/all/134336/",
        label="Example series",
    )
    adapter.capture_complete_listing_inventory(
        target=target,
        all_records=all_records,
        selected_records=owned_records,
        listing_identity="ebookjapan-series:134336",
    )

    assert [(row.source.external_id, row.source.global_display_position) for row in all_records] == [
        ("A000000001", 1),
        ("A000000002", 2),
        ("A000000003", 3),
    ]
    assert [(row.source.external_id, row.source.access_mode) for row in owned_records] == [
        ("A000000001", "owned"),
        ("A000000003", "owned"),
    ]
    assert owned_records[0].item.order_key is None
    assert owned_records[0].item.order_label is None
    assert (owned_records[1].item.order_key, owned_records[1].item.order_label) == ("3", "(3)")
    assert adapter.complete_listing_inventory is not None
    assert [
        (entry.external_id, entry.display_position, entry.in_scope)
        for entry in adapter.complete_listing_inventory.positions
    ] == [
        ("A000000001", 1, True),
        ("A000000002", 2, False),
        ("A000000003", 3, True),
    ]


@pytest.mark.parametrize(
    "row",
    [
        _row(0, "A000000001", "Example series", hidden_owned=True),
        _row(0, "A000000001", "Example series", owned=True, price="646円（税込）", basket_count=1),
        _row(0, "A000000001", "Example series", owned=True, conflicting_badge="試し読み"),
        _row(0, "A000000001", "Example series", price="0円（税込）", basket_count=1),
        _row(0, "A000000001", "Example series", price="646円（税込）", basket_count=2),
    ],
)
def test_unknown_or_conflicting_card_state_aborts_the_full_snapshot(row: dict[str, Any]) -> None:
    with pytest.raises(DiscoveryIncompleteError, match="ownership is unknown"):
        parse_ebookjapan_listing(_payload([row]), series_id="134336")


def test_foreign_duplicate_and_wrong_order_listings_fail_closed() -> None:
    owned = _row(0, "A000000001", "Example series", owned=True)
    foreign = _row(1, "A000000002", "Other series", owned=True)
    foreign["path"] = "/books/115888/A000000002/"
    payload = _payload([owned, foreign])
    payload["domPaths"] = [owned["path"], foreign["path"]]
    payload["layoutPaths"] = payload["domPaths"].copy()
    with pytest.raises(DiscoveryIncompleteError, match="belongs to another series"):
        parse_ebookjapan_listing(payload, series_id="134336")

    duplicate = _row(1, "A000000001", "Example series 2巻", owned=True)
    with pytest.raises(DiscoveryIncompleteError, match="duplicate product IDs"):
        parse_ebookjapan_listing(_payload([owned, duplicate]), series_id="134336")

    reversed_rows = [
        _row(0, "A000000001", "Example series（2）", owned=True),
        _row(1, "A000000002", "Example series（1）", owned=True),
    ]
    with pytest.raises(DiscoveryIncompleteError, match="conflict with native order"):
        parse_ebookjapan_listing(_payload(reversed_rows), series_id="134336")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accountAuthenticated", False),
        ("declaredTotal", 2),
        ("oldestFirst", False),
        ("paginationCount", 1),
        ("loadMoreCount", 1),
    ],
)
def test_full_parser_requires_authenticated_complete_oldest_first_native_listing(
    field: str,
    value: object,
) -> None:
    payload = _payload([_row(0, "A000000001", "Example series", owned=True)])
    payload[field] = value

    with pytest.raises(DiscoveryIncompleteError):
        parse_ebookjapan_listing(payload, series_id="134336")


def _source_card(
    product_id: str,
    *,
    purchased: bool = False,
    price_element: bool = False,
    wrapper: str = "",
) -> str:
    badge = '<span class="book-caption__tagtext">購入済み</span>' if purchased else ""
    price = '<div class="book-caption__price"></div>' if price_element else ""
    return (
        f"<{wrapper}>" if wrapper else ""
    ) + (
        '<li class="book-list__item">'
        f'<a class="book-item" href="/books/134336/{product_id}/"></a>'
        f'{badge}{price}'
        "</li>"
    ) + (f"</{wrapper}>" if wrapper else "")


def test_source_document_witness_records_only_explicit_owned_bits() -> None:
    html = (
        _source_card("A000000001", purchased=True)
        + _source_card("A000000002", price_element=True)
    )

    witnesses = parse_ebookjapan_source_witness(html, series_id="134336")

    assert [(row.external_id, row.owned) for row in witnesses] == [
        ("A000000001", True),
        ("A000000002", False),
    ]


@pytest.mark.parametrize(
    "html",
    [
        '<li class="book-list__item"><a class="book-item" href="/books/134336/A000000001/"></a></li>',
        _source_card("A000000001", purchased=True, price_element=True),
        _source_card("A000000001", purchased=True, wrapper="template"),
        _source_card("A000000001", purchased=True, wrapper="noscript"),
        _source_card("A000000001", purchased=True).replace(
            "</span></li>",
            "</span><span class=\"book-caption__tagtext\">購入済み</span></li>",
        ),
        _source_card("A000000001", purchased=True).replace(
            "<span class=\"book-caption__tagtext\"", "<span style=\"display:none\" class=\"book-caption__tagtext\""
        ),
        _source_card("A000000001", purchased=True).replace(
            '<li class="book-list__item">', '<div hidden><li class="book-list__item">'
        ).replace("</li>", "</li></div>"),
        _source_card("A000000001", price_element=True).replace(
            "class=\"book-caption__price\"", "class=\"book-caption__price\" hidden"
        ),
        _source_card("A000000001", purchased=True) * 2,
        _source_card("A000000001", price_element=True).replace(
            "/books/134336/", "/books/115888/"
        ),
    ],
)
def test_source_document_witness_rejects_incomplete_ambiguous_or_foreign_rows(html: str) -> None:
    with pytest.raises(DiscoveryIncompleteError):
        parse_ebookjapan_source_witness(html, series_id="134336")


def test_dynamic_rights_must_match_source_owned_bitset() -> None:
    owned = _row(0, "A000000001", "Example series", owned=True)
    not_owned = _row(
        1,
        "A000000002",
        "Example series 2巻",
        price="646円（税込）",
        basket_count=1,
    )
    witness = parse_ebookjapan_source_witness(
        _source_card("A000000001", purchased=True)
        + _source_card("A000000002", price_element=True),
        series_id="134336",
    )
    assert _source_rights_match(_payload([owned, not_owned]), witness)

    transient_not_owned = _row(
        0,
        "A000000001",
        "Example series",
        price="646円（税込）",
        basket_count=1,
    )
    assert not _source_rights_match(_payload([transient_not_owned, not_owned]), witness)

    reordered = _payload([not_owned, owned])
    assert not _source_rights_match(reordered, witness)

    wrong_path = _payload([owned, not_owned])
    wrong_path["domPaths"] = list(reversed(wrong_path["domPaths"]))
    assert not _source_rights_match(wrong_path, witness)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://ebookjapan.yahoo.co.jp/books/all/134336/", "134336"),
        ("https://ebookjapan.yahoo.co.jp/books/all/1/", "1"),
        ("https://ebookjapan.yahoo.co.jp/books/all/0/", None),
        ("https://ebookjapan.yahoo.co.jp/books/all/0134336/", None),
        ("https://ebookjapan.yahoo.co.jp/books/all/134336", None),
        ("https://ebookjapan.yahoo.co.jp/books/all/134336/?x=1", None),
        ("https://ebookjapan.yahoo.co.jp/books/all/134336/#top", None),
        ("https://www.ebookjapan.yahoo.co.jp/books/all/134336/", None),
        ("http://ebookjapan.yahoo.co.jp/books/all/134336/", None),
        ("https://ebookjapan.yahoo.co.jp.evil.test/books/all/134336/", None),
    ],
)
def test_series_url_parser_accepts_only_the_exact_full_list_form(url: str, expected: str | None) -> None:
    assert parse_ebookjapan_series_url(url) == expected
