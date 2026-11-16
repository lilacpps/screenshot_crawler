from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from playwright.async_api import Page

from screenshot_crawler.site_adapters.yanmaga.discovery import YanmagaEpisodeParts
from screenshot_crawler.site_adapters.yanmaga.rental_history import (
    RentalCountdown,
    RentalHistoryObservation,
    fetch_rental_history_countdowns,
    fetch_rental_history_observations,
    parse_rental_history_html,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")

TARGET = YanmagaEpisodeParts("work", "0123456789abcdef0123456789abcdef")
OBSERVED = datetime(2026, 11, 15, 3, 10, 49, tzinfo=UTC)

# Test-owned tokens copied from the sanitized native-structure probe. These are
# deliberately independent of production constants so selector drift fails.
TEST_LABEL_CLASSES = frozenset(
    {
        "tw:flex", "tw:items-center", "tw:justify-center", "tw:px-1.75",
        "tw:py-9xs", "tw:border", "tw:box-border", "tw:border-gray-gallery",
        "tw:w-17.5", "tw:h-4", "tw:text-body-4xs-b", "tw:xl:w-19",
        "tw:xl:h-4.5", "tw:xl:text-body-3xs-bold",
    }
)
TEST_VALUE_CLASSES = frozenset(
    {
        "tw:flex", "tw:items-center", "tw:justify-center", "tw:px-6xs",
        "tw:py-9xs", "tw:text-center", "tw:text-nowrap", "tw:bg-red-crimson",
        "tw:text-white", "tw:w-16", "tw:h-4", "tw:text-body-4xs-b",
        "tw:xl:w-18", "tw:xl:h-4.5", "tw:xl:text-body-3xs-bold",
    }
)
TEST_PAIR_PARENT_CLASSES = frozenset(
    {"tw:flex", "tw:items-center", "tw:justify-center", "tw:w-fit"}
)
TEST_ANCESTOR_CLASSES = (
    frozenset(
        {"tw:flex", "tw:justify-between", "tw:items-center", "tw:gap-7xs", "tw:h-4", "tw:xl:h-4.5"}
    ),
    frozenset(
        {"tw:relative", "tw:flex", "tw:flex-col", "tw:gap-y-8xs", "tw:xl:gap-y-7xs"}
    ),
    frozenset(
        {"tw:flex", "tw:flex-col", "tw:flex-1", "tw:min-w-0", "tw:w-full", "tw:gap-7xs", "tw:xl:gap-5xs"}
    ),
    frozenset(
        {
            "tw:flex", "tw:bg-white", "tw:relative", "tw:border-b", "tw:hover:opacity-50",
            "tw:has-[button:hover]:opacity-100", "tw:gap-6xs", "tw:px-6xs", "tw:py-7xs",
            "tw:w-full", "tw:border-gray-mercury", "tw:xl:flex-col", "tw:xl:gap-5xs",
            "tw:xl:p-8xs", "tw:xl:w-[238px]", "tw:xl:border-transparent",
        }
    ),
)
TEST_ANCHOR_CLASSES = frozenset({"tw:no-underline", "tw:text-inherit"})
TEST_HISTORY_LINK_CLASSES = frozenset(
    {"tw:text-button-sm", "tw:text-center", "tw:h-8", "tw:text-gray-dusty-dark", "tw:pb-[11px]"}
)
TEST_RENTAL_COLLECTION_CLASSES = frozenset(
    {"tw:grid", "tw:grid-cols-1", "tw:xl:grid-cols-4", "tw:xl:gap-4xs", "tw:md:py-xs"}
)


def _card(
    *,
    label: str = "\u30ec\u30f3\u30bf\u30eb\u671f\u9593",
    value: str = "\u6b8b\u308a22\u6642\u9593",
    hidden: str = "",
    hidden_class: str = "",
    hidden_style: str = "",
    episode_id: str = TARGET.episode_id,
    label_classes: frozenset[str] = TEST_LABEL_CLASSES,
    value_classes: frozenset[str] = TEST_VALUE_CLASSES,
) -> str:
    label_class_text = " ".join(sorted(label_classes))
    value_class_text = " ".join(sorted(value_classes))
    parent_classes = " ".join(
        sorted(TEST_PAIR_PARENT_CLASSES | ({hidden_class} if hidden_class else set()))
    )
    outer_classes = [" ".join(sorted(classes)) for classes in TEST_ANCESTOR_CLASSES]
    anchor_classes = " ".join(sorted(TEST_ANCHOR_CLASSES))
    target = f"/comics/work/{episode_id}"
    return (
        f'<a class="{anchor_classes}" href="{target}"><h2>{label} {value}</h2>'
        f'<div class="{outer_classes[3]}"><div class="{outer_classes[2]}">'
        f'<div class="{outer_classes[1]}"><div class="{outer_classes[0]}">'
        f'<div class="{parent_classes}" {hidden} {hidden_style}>'
        f'<div class="{label_class_text}">{label}</div>'
        f'<div class="{value_class_text}">{value}</div>'
        "</div></div></div></div></div></a>"
    )


def _history_link(
    *,
    label: str = "\u30ec\u30f3\u30bf\u30eb\u5c65\u6b74",
    href: str = "/mypage?tab=rental",
    class_tokens: frozenset[str] = TEST_HISTORY_LINK_CLASSES,
    target: str | None = None,
    style: str = "",
) -> str:
    classes = " ".join(sorted(class_tokens))
    target_attr = "" if target is None else f' target="{target}"'
    style_attr = "" if not style else f' style="{style}"'
    return f'<a class="{classes}" href="{href}"{target_attr}{style_attr}>{label}</a>'


async def _run_runtime_history_probe(
    page: Page,
    *,
    history_links: str,
    bad_history_headers: str | None = None,
    history_cards: str | None = None,
    pagination: str = "",
) -> tuple[tuple[tuple[str, RentalCountdown], ...], tuple[str, ...]]:
    requests: list[str] = []

    async def route_handler(route) -> None:
        parsed = urlsplit(route.request.url)
        requests.append(parsed.path + parsed.query)
        headers = {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "private, max-age=0, must-revalidate",
            "date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if parsed.path == "/comics/work":
            body = "<html><body>work fixture</body></html>"
        elif parsed.path == "/mypage" and not parsed.query:
            body = "<html><body>" + history_links + "</body></html>"
        elif parsed.path == "/mypage" and parsed.query == "tab=rental":
            cards = _card() if history_cards is None else history_cards
            body = (
                "<html><body><ul id=\"content_card_list\" class=\""
                + " ".join(sorted(TEST_RENTAL_COLLECTION_CLASSES))
                + "\">"
                + cards
                + "</ul>"
                + pagination
                + "</body></html>"
            )
            if bad_history_headers == "age":
                headers["age"] = "0"
            elif bad_history_headers == "invalid_date":
                headers["date"] = "yesterday"
            elif bad_history_headers == "stale_date":
                headers["date"] = (datetime.now(UTC) - timedelta(seconds=30)).strftime(
                    "%a, %d %b %Y %H:%M:%S GMT"
                )
            elif bad_history_headers == "cache_control":
                headers["cache-control"] = "public, max-age=0, must-revalidate"
            elif bad_history_headers == "duplicate_cache_control":
                headers["cache-control"] = "private, private, max-age=0, must-revalidate"
            elif bad_history_headers == "mime":
                headers["content-type"] = "application/json"
            elif bad_history_headers == "missing_date":
                del headers["date"]
        else:
            await route.abort()
            return
        await route.fulfill(status=200, headers=headers, body=body)

    await page.route("**/*", route_handler)
    await page.goto("https://yanmaga.jp/comics/work?sort=older", wait_until="domcontentloaded")
    proofs = await fetch_rental_history_countdowns(
        page,
        observed_mypage_href="https://yanmaga.jp/mypage",
        targets=(TARGET,),
    )
    return proofs, tuple(requests)


async def _run_runtime_history_observation_probe(
    page: Page,
    *,
    history_cards: str,
    outside_cards: str = "",
    pagination: str = "",
    max_countdown_hours: int = 23,
):
    requests: list[str] = []

    async def route_handler(route) -> None:
        parsed = urlsplit(route.request.url)
        requests.append(parsed.path + parsed.query)
        headers = {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "private, max-age=0, must-revalidate",
            "date": datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        if parsed.path == "/comics/work":
            body = "<html><body>work fixture</body></html>"
        elif parsed.path == "/mypage" and not parsed.query:
            body = "<html><body>" + _history_link() + "</body></html>"
        elif parsed.path == "/mypage" and parsed.query == "tab=rental":
            body = (
                "<html><body><ul id=\"content_card_list\" class=\""
                + " ".join(sorted(TEST_RENTAL_COLLECTION_CLASSES))
                + "\">"
                + history_cards
                + "</ul>"
                + outside_cards
                + pagination
                + "</body></html>"
            )
        else:
            await route.abort()
            return
        await route.fulfill(status=200, headers=headers, body=body)

    await page.route("**/*", route_handler)
    await page.goto("https://yanmaga.jp/comics/work?sort=older", wait_until="domcontentloaded")
    observations = await fetch_rental_history_observations(
        page,
        observed_mypage_href="https://yanmaga.jp/mypage",
        targets=(TARGET,),
        max_countdown_hours=max_countdown_hours,
    )
    return observations, requests


async def test_yanmaga_rental_history_observations_distinguish_active_and_verified_absent(
    browser_page: Page,
) -> None:
    active, active_requests = await _run_runtime_history_observation_probe(
        browser_page, history_cards=f'<li data-index="0">{_card()}</li>'
    )
    assert active == (
        RentalHistoryObservation(
            external_id=f"{TARGET.slug}:{TARGET.episode_id}",
            countdown=active[0].countdown if active else None,
        ),
    )
    assert active[0].countdown is not None
    assert active[0].countdown.remaining_hours == 22
    assert active_requests[1:] == ["/mypage", "/mypagetab=rental"]

    other_id = "1123456789abcdef0123456789abcdef"
    absent, absent_requests = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=f'<li data-index="0">{_card(episode_id=other_id)}</li>',
    )
    assert absent == (RentalHistoryObservation(f"{TARGET.slug}:{TARGET.episode_id}", None),)
    assert absent_requests[1:] == ["/mypage", "/mypagetab=rental"]


async def test_yanmaga_wait_rental_history_allows_observed_72_hour_countdown_only_when_requested(
    browser_page: Page,
) -> None:
    standard, _ = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=f'<li data-index="0">{_card(value="\u6b8b\u308a72\u6642\u9593")}</li>',
    )
    assert standard is None

    wait, _ = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=f'<li data-index="0">{_card(value="\u6b8b\u308a72\u6642\u9593")}</li>',
        max_countdown_hours=72,
    )
    assert wait is not None
    countdown = wait[0].countdown
    assert countdown is not None
    assert countdown.remaining_hours == 72
    assert countdown.access_granted_until is not None
    assert countdown.access_granted_until == (
        countdown.observed_at + timedelta(hours=71) - timedelta(seconds=5)
    )


@pytest.mark.parametrize("days", (1, 2, 3))
async def test_yanmaga_wait_rental_history_parses_native_days_with_day_lower_bound(
    browser_page: Page, days: int
) -> None:
    day_text = f"\u6b8b\u308a{days}\u65e5"
    cards = f'<li data-index="0">{_card(value=day_text)}</li>'
    ordinary, _ = await _run_runtime_history_observation_probe(
        browser_page, history_cards=cards, max_countdown_hours=23
    )
    assert ordinary is None

    wait, _ = await _run_runtime_history_observation_probe(
        browser_page, history_cards=cards, max_countdown_hours=72
    )
    assert wait is not None
    countdown = wait[0].countdown
    assert countdown is not None
    assert countdown.active is True
    assert countdown.remaining_hours == 0
    assert countdown.remaining_days == days
    if days == 1:
        assert countdown.access_granted_until is None
        assert countdown.expiry_evidence is None
    else:
        assert countdown.access_granted_until == (
            countdown.observed_at + timedelta(days=days - 1) - timedelta(seconds=5)
        )
        assert countdown.expiry_evidence == "site_day_countdown_lower_bound"


async def test_yanmaga_wait_rental_history_rejects_days_beyond_requested_bound(
    browser_page: Page,
) -> None:
    day_text = "\u6b8b\u308a4\u65e5"
    observations, _ = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=f'<li data-index="0">{_card(value=day_text)}</li>',
        max_countdown_hours=72,
    )

    assert observations is None


async def test_yanmaga_rental_history_incomplete_collection_is_unknown(
    browser_page: Page,
) -> None:
    observations, requests = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=f'<li data-index="0">{_card()}</li>',
        pagination='<button>More</button>',
    )

    assert observations is None
    assert requests[1:] == ["/mypage", "/mypagetab=rental"]


@pytest.mark.parametrize(
    ("history_cards", "outside_cards"),
    [
        (
            f'<li data-index="0">{_card(episode_id="1123456789abcdef0123456789abcdef")}</li>',
            _card(),
        ),
        (
            f'<li data-index="0">{_card()}</li>',
            _card(),
        ),
        (
            f'<li data-index="0">{_card(episode_id="1123456789abcdef0123456789abcdef")}</li>',
            (
                '<ul class="other">'
                f'<li data-index="0">{_card()}</li>'
                "</ul>"
            ),
        ),
    ],
    ids=("target-outside-known-list", "target-duplicated-outside-list", "decoy-list"),
)
async def test_yanmaga_rental_history_target_outside_collection_is_unknown(
    browser_page: Page, history_cards: str, outside_cards: str
) -> None:
    observations, _requests = await _run_runtime_history_observation_probe(
        browser_page,
        history_cards=history_cards,
        outside_cards=outside_cards,
    )

    assert observations is None


async def test_yanmaga_runtime_rental_history_helper_fetches_observed_native_ui_links(
    browser_page: Page,
) -> None:
    proofs, requests = await _run_runtime_history_probe(browser_page, history_links=_history_link())

    assert len(proofs) == 1
    external_id, countdown = proofs[0]
    assert external_id == f"{TARGET.slug}:{TARGET.episode_id}"
    assert countdown.remaining_hours == 22
    assert countdown.active is True
    assert countdown.access_granted_until == (
        countdown.observed_at - timedelta(seconds=5) + timedelta(hours=21)
    )
    assert len(requests) == 3
    assert requests[1:] == ("/mypage", "/mypagetab=rental")


@pytest.mark.parametrize(
    "history_links",
    [
        _history_link() + _history_link(),
        _history_link(style="display:none!important"),
        _history_link(href="/mypage?tab=other&tab=rental"),
        _history_link(label="prefix \u30ec\u30f3\u30bf\u30eb\u5c65\u6b74 suffix"),
        _history_link(class_tokens=TEST_HISTORY_LINK_CLASSES | {"unknown-class"}),
        _history_link(target="_blank"),
    ],
    ids=("duplicate-same-href", "hidden-link", "duplicate-tab", "inexact-label", "unknown-class", "new-tab"),
)
async def test_yanmaga_runtime_history_helper_rejects_ambiguous_ui_before_history_get(
    browser_page: Page, history_links: str
) -> None:
    proofs, requests = await _run_runtime_history_probe(browser_page, history_links=history_links)

    assert proofs == ()
    assert requests[1:] == ("/mypage",)


@pytest.mark.parametrize(
    "bad_headers",
    (
        "age", "invalid_date", "stale_date", "cache_control", "duplicate_cache_control",
        "mime", "missing_date",
    ),
)
async def test_yanmaga_runtime_history_helper_rejects_nonfresh_metadata_headers(
    browser_page: Page, bad_headers: str
) -> None:
    proofs, requests = await _run_runtime_history_probe(
        browser_page, history_links=_history_link(), bad_history_headers=bad_headers
    )

    assert proofs == ()
    assert requests[1:] == ("/mypage", "/mypagetab=rental")


async def test_yanmaga_rental_history_parser_binds_exact_native_target_card(
    browser_page: Page,
) -> None:
    await browser_page.set_content("<html><body></body></html>")

    result = await parse_rental_history_html(
        browser_page, "<html><body>" + _card() + "</body></html>", target=TARGET, observed_at=OBSERVED
    )

    assert result is not None
    assert result.remaining_hours == 22
    assert result.active is True
    assert result.expiry_evidence is None
    assert result.access_granted_until is None


@pytest.mark.parametrize(
    "html",
    [
        (
            "<html><body><a href='/comics/work/0123456789abcdef0123456789abcdef'>"
            "<h2>\\u30ec\\u30f3\\u30bf\\u30eb\\u671f\\u9593 \\u6b8b\\u308a22\\u6642\\u9593</h2></a></body></html>"
        ),
        "<html><body>" + _card(episode_id="1123456789abcdef0123456789abcdef") + "</body></html>",
        "<html><body>" + _card() + _card() + "</body></html>",
        "<html><body>" + _card(value_classes=TEST_VALUE_CLASSES | {"new-token"}) + "</body></html>",
        "<html><body>" + _card(label_classes=TEST_LABEL_CLASSES | {"new-token"}) + "</body></html>",
        "<html><body>" + _card(hidden="hidden") + "</body></html>",
        "<html><body>" + _card(hidden_class="hidden") + "</body></html>",
        "<html><body>" + _card(hidden_style='style="display:none!important"') + "</body></html>",
        "<html><body>" + _card(hidden_style='style="opacity:0.0"') + "</body></html>",
        "<html><body>" + _card(label="\\u7ae0\\u30bf\\u30a4\\u30c8\\u30eb") + "</body></html>",
        "<html><body>" + _card(value="\\u6b8b\\u308a\u306a\u3057") + "</body></html>",
    ],
    ids=(
        "title-decoy-only", "wrong-target", "duplicate-target", "unknown-value-class",
        "unknown-label-class", "hidden", "hide-class", "display-none-important",
        "opacity-zero", "wrong-label", "unknown-value",
    ),
)
async def test_yanmaga_rental_history_parser_rejects_ambiguous_or_decoy_fields(
    browser_page: Page, html: str
) -> None:
    await browser_page.set_content("<html><body></body></html>")

    result = await parse_rental_history_html(browser_page, html, target=TARGET, observed_at=OBSERVED)

    assert result is None


async def test_yanmaga_rental_history_one_hour_is_active_without_finite_lower_bound(
    browser_page: Page,
) -> None:
    await browser_page.set_content("<html><body></body></html>")

    result = await parse_rental_history_html(
        browser_page,
        "<html><body>" + _card(value="\u6b8b\u308a1\u6642\u9593") + "</body></html>",
        target=TARGET,
        observed_at=OBSERVED,
    )

    assert result is not None
    assert result.active is True
    assert result.access_granted_until is None
    assert result.expiry_evidence is None
