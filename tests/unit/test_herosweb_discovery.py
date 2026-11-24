from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from playwright.async_api import Error as PlaywrightError

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.discovery import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.herosweb import discovery as discovery_module
from screenshot_crawler.site_adapters.herosweb.adapter import (
    HeroswebAdapter,
    HeroswebEpisodeRouteGuard,
)
from screenshot_crawler.site_adapters.herosweb.discovery import (
    HeroswebDiscoveryAdapter,
    _classify_access,
    _CurrentDocumentAuth,
    _records_from_rows,
    _rental_remaining,
    _validate_snapshot,
    _validate_work_header_snapshot,
    _work_title,
    parse_herosweb_episode_url,
    parse_herosweb_work_url,
    parse_range_map,
)

WORK_ID = "0f023839d7bca"
BASE = f"https://heros-web.com/series/{WORK_ID}"


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Fixture Work", "Fixture Work"),
        (" HERO'S Web（ヒーローズウェブ）公式サイトの　架空作品 ", "架空作品"),
        ("架空作品 HERO'S Web（ヒーローズウェブ）公式サイトの続き",
         "架空作品 HERO'S Web（ヒーローズウェブ）公式サイトの続き"),
        ("HERO'S Web（ヒーローズウェブ）公式サイトの", ""),
    ],
)
def test_herosweb_work_title_removes_only_the_leading_boilerplate(
    heading: str, expected: str,
) -> None:
    assert _work_title(heading) == expected


def _access_node(
    tag: str,
    *,
    classes: tuple[str, ...] = (),
    text: str = "",
    children: tuple[dict[str, object], ...] = (),
    data_e2e: str = "",
    data_attributes: tuple[str, ...] = (),
    url: dict[str, str] | None = None,
    alt: str = "",
) -> dict[str, object]:
    return {
        "tag": tag,
        "classTokens": sorted(classes),
        "text": text,
        "id": "",
        "role": "",
        "title": "",
        "ariaLabel": "",
        "dataE2e": data_e2e,
        "dataAttributes": list(data_attributes),
        "alt": alt,
        "url": url,
        "children": list(children),
    }


def _free_access_children(label: str = "無料") -> list[dict[str, object]]:
    marker = "eliFreeBadge" if label == "無料" else "eliMemFreeBadge"
    return [
        _access_node(
            "DIV",
            children=(
                _access_node(
                    "SPAN",
                    classes=("mode-free", "series-eplist-item-access-text"),
                    text=label,
                    data_e2e=marker,
                    data_attributes=("data-e2e",),
                ),
            ),
        )
    ]


def _paid_access_children(price: str) -> list[dict[str, object]]:
    return [
        _access_node(
            "DIV",
            children=(
                _access_node(
                    "DIV",
                    classes=("series-eplist-item-access-paid",),
                    children=(
                        _access_node(
                            "SPAN",
                            classes=("series-eplist-item-access-paid-item",),
                            text=price,
                            data_e2e="eliPrice",
                            data_attributes=("data-e2e",),
                            children=(
                                _access_node(
                                    "IMG",
                                    alt="コイン",
                                    data_e2e="eliCoinIcon",
                                    data_attributes=("data-e2e", "data-nimg"),
                                    url={"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"},
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
    ]


def _quota_access_children() -> list[dict[str, object]]:
    markers = (
        ("eliWfIcon", ("series-eplist-item-access-icon",)),
        ("eliIfIcon", ("series-eplist-item-access-icon",)),
    )
    return [
        _access_node(
            "DIV",
            children=tuple(
                _access_node(
                    "SVG",
                    classes=classes,
                    data_e2e=marker,
                    data_attributes=("data-e2e",),
                    children=(_access_node("PATH"),),
                )
                for marker, classes in markers
            ),
        )
    ]


def _rental_row(label: str = "レンタル中 閲覧期限 2日+23時間") -> dict[str, object]:
    return {
        **_snapshot_row(),
        "accessText": label,
        "freeLabels": [{"text": label, "modeFree": False}],
        "accessChildren": [_access_node("DIV", children=(
            _access_node(
                "SPAN", classes=("series-eplist-item-access-text",), text=label,
                data_e2e="eliRentStat", data_attributes=("data-e2e",),
                children=(_access_node("BR"), _access_node("BR")),
            ),
        ))],
    }


@pytest.mark.parametrize(
    ("label", "hours"),
    [("レンタル中 閲覧期限 14日+23時間", 358),
     ("レンタル中 閲覧期限 2日+23時間", 70),
     ("レンタル中 閲覧期限 0日+1時間", 0),
     ("レンタル中 閲覧期限 0日+0時間", 0)],
)
def test_authenticated_rental_uses_quota_and_finite_conservative_grant(label, hours):
    raw = _rental_row(label)
    assert _classify_access(raw, authenticated=False) == "unknown"
    assert _classify_access(raw, authenticated=True) == "quota"
    assert _rental_remaining(raw, authenticated=True) == timedelta(hours=hours)
    observed_at = datetime.fromisoformat("2026-11-24T12:00:00+09:00")
    row = HeroswebDiscoveryAdapter._parse_row(
        raw, first_position=61, work_id=WORK_ID, authenticated=True,
    )
    source = _records_from_rows(
        [row], work_id=WORK_ID, work_title="Fixture Work", observed_at=observed_at,
    )[0].source
    assert source.access_granted_until == (
        observed_at + timedelta(hours=hours) if hours else None
    )
    assert source.access_granted_until_observed is True


@pytest.mark.parametrize("fault", ["marker", "class", "breaks", "extra", "quota", "paid", "hours", "days"])
def test_rental_rejects_unobserved_or_conflicting_access_tree(fault):
    raw = deepcopy(_rental_row())
    label_node = raw["accessChildren"][0]["children"][0]
    if fault == "marker":
        label_node["dataE2e"] = "eliMemFreeBadge"
    elif fault == "class":
        label_node["classTokens"].append("mode-free")
    elif fault == "breaks":
        label_node["children"].pop()
    elif fault == "extra":
        raw["accessChildren"].append(_access_node("SPAN"))
    elif fault == "quota":
        raw["quotaIcons"] = [{"dataE2e": "eliWfIcon"}]
    elif fault == "paid":
        raw["paidParents"] = ["series-eplist-item-access-paid"]
    else:
        raw = _rental_row("レンタル中 閲覧期限 2日+24時間" if fault == "hours"
                          else "レンタル中 閲覧期限 99日+0時間")
    assert _classify_access(raw, authenticated=True) == "unknown"
    assert _rental_remaining(raw, authenticated=True) is None


def test_herosweb_urls_reject_unsafe_or_ambiguous_inputs() -> None:
    assert parse_herosweb_work_url(BASE) == WORK_ID
    assert parse_herosweb_work_url(f"{BASE}/") == WORK_ID
    assert parse_herosweb_episode_url("https://heros-web.com/episodes/4fe9831c6f540") == (
        "4fe9831c6f540"
    )
    for value in (
        f"http://heros-web.com/series/{WORK_ID}",
        f"https://www.heros-web.com/series/{WORK_ID}",
        f"https://example.com/series/{WORK_ID}",
        f"https://user@heros-web.com/series/{WORK_ID}",
        f"https://heros-web.com:444/series/{WORK_ID}",
        f"{BASE}?page=1",
        f"{BASE}#reader",
        f"{BASE}?",
        f"{BASE}/1",
        "https://heros-web.com/series/not-an-id",
    ):
        assert parse_herosweb_work_url(value) is None
    assert HeroswebDiscoveryAdapter().resolve_registration_url(f"{BASE}?tracking=1").status == "blocked"


def test_herosweb_range_map_requires_complete_contiguous_routes() -> None:
    entries = [
        {"label": "最新話から", "href": f"{BASE}/new", "class": "series-sort-link mode-new"},
        {"label": "1-30", "href": f"{BASE}/1", "class": "series-sort-link"},
        {"label": "31-47", "href": f"{BASE}/2", "class": "series-sort-link"},
    ]
    ranges = parse_range_map(entries, work_id=WORK_ID)
    assert [(item.page_number, item.start_position, item.end_position) for item in ranges] == [
        (1, 1, 30),
        (2, 31, 47),
    ]
    invalid = (
        [*entries[:2], {**entries[2], "label": "32-47"}],
        [*entries[:2], {**entries[2], "href": "https://heros-web.com/series/aaaaaaaaaaaaa/2"}],
        [*entries[:2], {"label": "...", "href": "", "class": "series-sort-link"}],
    )
    for candidate in invalid:
        with pytest.raises(DiscoveryIncompleteError):
            parse_range_map(candidate, work_id=WORK_ID)


def test_herosweb_current_range_alias_is_only_allowed_when_selected() -> None:
    entries = [
        {"label": "最新話から", "href": f"{BASE}/new", "class": "series-sort-link mode-new"},
        {"label": "1-30", "href": BASE, "class": "series-sort-link mode-current"},
        {"label": "31-47", "href": f"{BASE}/2", "class": "series-sort-link"},
    ]
    ranges = parse_range_map(entries, work_id=WORK_ID)
    assert [item.path for item in ranges] == [
        f"/series/{WORK_ID}/1",
        f"/series/{WORK_ID}/2",
    ]
    with pytest.raises(DiscoveryIncompleteError):
        parse_range_map(
            [entries[0], {**entries[1], "class": "series-sort-link"}, entries[2]],
            work_id=WORK_ID,
        )


@pytest.mark.parametrize("prefix", ["", "HERO'S Web（ヒーローズウェブ）公式サイトの"])
def test_herosweb_work_header_validation_does_not_treat_preview_roots_as_inventory(
    prefix: str,
) -> None:
    snapshot = {
        "canonicalCount": 1,
        "canonicals": [BASE],
        "titles": [f"{prefix}Fixture Work"],
        "mainCount": 1,
        "rangeContainerCount": 1,
        "rangeLinks": [
            {
                "label": "最新話から",
                "href": f"{BASE}/new",
                "class": "series-sort-link mode-new",
            },
            {"label": "1-30", "href": f"{BASE}/1", "class": "series-sort-link"},
            {"label": "31-47", "href": f"{BASE}/2", "class": "series-sort-link"},
        ],
        # Work-top previews can be incomplete or structurally ambiguous. They are
        # deliberately not part of this header/range proof.
        "rootCount": 2,
        "roots": [{"unexpected": True}, {"unexpected": True}],
        "allRowCount": 2,
    }

    title, ranges = _validate_work_header_snapshot(
        snapshot, expected_url=BASE, work_id=WORK_ID
    )
    assert title == "Fixture Work"
    assert [(item.start_position, item.end_position, item.path) for item in ranges] == [
        (1, 30, f"/series/{WORK_ID}/1"),
        (31, 47, f"/series/{WORK_ID}/2"),
    ]

    with pytest.raises(DiscoveryIncompleteError):
        _validate_work_header_snapshot(
            {**snapshot, "canonicals": [f"{BASE}/1"]},
            expected_url=BASE,
            work_id=WORK_ID,
        )

    with pytest.raises(DiscoveryIncompleteError):
        _validate_work_header_snapshot(
            {**snapshot, "titles": ["HERO'S Web（ヒーローズウェブ）公式サイトの"]},
            expected_url=BASE,
            work_id=WORK_ID,
        )


def test_herosweb_access_classification_is_exact_and_fail_closed() -> None:
    assert _classify_access(
        {"accessCount": 1, "accessText": "無料", "freeLabels": [{"text": "無料", "modeFree": True}],
         "paidParents": [], "paidItems": [], "quotaIcons": [],
         "accessChildren": _free_access_children()}
    ) == "free"
    assert _classify_access(
        {"accessCount": 1, "accessText": "今なら無料", "freeLabels": [{"text": "今なら無料", "modeFree": True}],
         "paidParents": [], "paidItems": [], "quotaIcons": [],
         "accessChildren": _free_access_children("今なら無料")}
    ) == "unknown"
    now_free = {
        "accessCount": 1, "accessText": "今なら無料",
        "freeLabels": [{"text": "今なら無料", "modeFree": True}],
        "paidParents": [], "paidItems": [], "quotaIcons": [],
        "accessChildren": _free_access_children("今なら無料"),
    }
    assert _classify_access(now_free, authenticated=True) == "free"
    assert _classify_access({**now_free, "quotaIcons": [{"dataE2e": "eliWfIcon"}]}, authenticated=True) == "unknown"
    plain_free = {
        "accessCount": 1, "accessText": "無料",
        "freeLabels": [{"text": "無料", "modeFree": True}],
        "paidParents": [], "paidItems": [], "quotaIcons": [],
        "accessChildren": _free_access_children(),
    }
    free_wrapper = _free_access_children()[0]
    free_wrapper_children = free_wrapper["children"]
    assert isinstance(free_wrapper_children, list)
    for conflicting in (
        {**plain_free, "accessText": "無料 チケット"},
        {**plain_free, "accessChildren": [_access_node("DIV", children=(
            *free_wrapper_children, _access_node("SPAN", text="チケット")
        ))]},
        {**plain_free, "accessChildren": [_access_node("DIV", children=(
            _access_node("SPAN", classes=("mode-free", "series-eplist-item-access-text"), text="無料"),
            _access_node("IMG", url={"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"}),
        ))]},
    ):
        assert _classify_access(conflicting) == "unknown"

    paid_shape = _paid_access_children("90")
    paid_wrapper = paid_shape[0]
    paid_div_children = paid_wrapper["children"]
    assert isinstance(paid_div_children, list)
    paid_item_children = paid_div_children[0]["children"]
    assert isinstance(paid_item_children, list)
    paid_item = paid_div_children[0]
    assert isinstance(paid_item, dict)
    extra_coin = _access_node("IMG", url={"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"})
    paid_with_extra_image = _access_node(
        "DIV", classes=("series-eplist-item-access-paid",),
        children=(_access_node("SPAN", classes=("series-eplist-item-access-paid-item",),
                               text="90", children=(*paid_item_children, extra_coin)),),
    )
    paid_record = {
        "accessCount": 1, "accessText": "90", "freeLabels": [],
        "paidParents": ["series-eplist-item-access-paid"], "quotaIcons": [],
        "accessChildren": [paid_with_extra_image],
        "paidItems": [{"parentClass": "series-eplist-item-access-paid", "directText": "90",
                       "images": [{"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"}]}],
    }
    assert _classify_access(paid_record) == "unknown"
    for price in ("60", "90", "120"):
        assert _classify_access(
            {
                "accessCount": 1,
                "accessText": price,
                "freeLabels": [],
                "paidParents": ["series-eplist-item-access-paid"],
                "quotaIcons": [],
                "accessChildren": _paid_access_children(price),
                "paidItems": [
                    {
                        "parentClass": "series-eplist-item-access-paid",
                        "directText": price,
                        "images": [{"origin": "https://heros-web.com", "path": "/images/icons/coin.svg"}],
                    }
                ],
            }
        ) == "paid"
    for text, path in (("0", "/images/icons/coin.svg"),
                       ("90", "/images/icons/ticket.svg"),
                       ("", "/images/icons/coin.svg")):
        assert _classify_access(
            {
                "accessCount": 1,
                "accessText": text,
                "freeLabels": [],
                "paidParents": ["series-eplist-item-access-paid"],
                "quotaIcons": [],
                "accessChildren": _paid_access_children(text),
                "paidItems": [
                    {
                        "parentClass": "series-eplist-item-access-paid",
                        "directText": text,
                        "images": [{"origin": "https://heros-web.com", "path": path}],
                    }
                ],
            }
        ) == "unknown"
    assert _classify_access(
        {"accessCount": 1, "accessText": "", "freeLabels": [], "paidParents": [],
         "paidItems": [], "quotaIcons": [], "accessChildren": []}
    ) == "unknown"


def test_herosweb_quota_requires_exact_paired_access_svg_markers() -> None:
    icons = [
        {"class": "series-eplist-item-access-icon", "dataE2e": "eliWfIcon"},
        {"class": "series-eplist-item-access-icon", "dataE2e": "eliIfIcon"},
    ]
    badge = {
        "accessCount": 1,
        "accessText": "",
        "freeLabels": [],
        "paidParents": [],
        "paidItems": [],
        "quotaIcons": icons,
        "accessChildren": _quota_access_children(),
    }
    assert _classify_access(badge) == "quota"
    for invalid in (
        {**badge, "quotaIcons": icons[:1]},
        {**badge, "quotaIcons": [*icons, icons[1]]},
        {**badge, "quotaIcons": [{**icons[0], "dataE2e": "unknown"}, icons[1]]},
        {**badge, "freeLabels": [{"text": "無料", "modeFree": True}]},
        {**badge, "accessText": "conflict"},
        {**badge, "accessChildren": [*_quota_access_children(), _access_node("SPAN", text="無料") ]},
        {**badge, "accessChildren": [_access_node("DIV", children=(
            _access_node("SPAN", text="無料"),
            *_quota_access_children()[0]["children"],
        ))]},
    ):
        assert _classify_access(invalid) == "unknown"


async def test_herosweb_auth_response_must_belong_to_current_document_generation() -> None:
    class EventPage:
        def __init__(self) -> None:
            self.listeners: dict[str, object] = {}

        def on(self, event: str, callback) -> None:
            self.listeners[event] = callback

        def remove_listener(self, event: str, callback) -> None:
            if self.listeners.get(event) is callback:
                self.listeners.pop(event)

    class Request:
        def __init__(self, document_url: str) -> None:
            self.url = "https://heros-web.com/api/auth/session"
            self.method = "GET"
            self.frame = type("Frame", (), {"url": document_url})()

    class Response:
        def __init__(self, request: Request, payload: dict[str, object]) -> None:
            self.request = request
            self.url = request.url
            self.status = 200
            self.headers: dict[str, str] = {}
            self.payload = payload

        async def body(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    page = EventPage()
    auth = _CurrentDocumentAuth(page)  # type: ignore[arg-type]
    work_url = f"https://heros-web.com/series/{WORK_ID}"
    range_url = f"{work_url}/1"
    auth.begin_document(work_url)
    stale_request = Request(work_url)
    auth._on_request(stale_request)
    assert id(stale_request) in auth._request_bindings

    auth.begin_document(range_url)
    auth._on_response(Response(stale_request, {"user": {"fixture": "old"}}))
    assert auth.session_user_present is None

    current_request = Request(range_url)
    auth._on_request(current_request)
    auth._on_response(Response(current_request, {"user": None}))
    await auth.wait_for_current_response()
    assert auth.session_user_present is False
    await auth.close()


@pytest.mark.parametrize("controlled", [False, True])
async def test_herosweb_route_coverage_is_current_page_scoped_and_fails_closed(
    controlled: bool,
) -> None:
    class CurrentPage:
        main_frame = object()

        async def evaluate(self, _script: str):
            return {"supported": True, "controlled": controlled}

    page = CurrentPage()
    episode_url = f"https://heros-web.com/episodes/{'a' * 13}"
    adapter = HeroswebAdapter()

    if controlled:
        with pytest.raises(UnknownPageStateError, match="service-worker-controlled"):
            await adapter._assert_no_service_worker_controller(page)  # type: ignore[arg-type]
        with pytest.raises(DiscoveryIncompleteError, match="service-worker-controlled"):
            await discovery_module._assert_no_service_worker_controller(page)  # type: ignore[arg-type]
    else:
        await adapter._assert_no_service_worker_controller(page)  # type: ignore[arg-type]
        await discovery_module._assert_no_service_worker_controller(page)  # type: ignore[arg-type]

    episode_guard = HeroswebEpisodeRouteGuard(page, episode_id="a" * 13)  # type: ignore[arg-type]
    discovery_guard = discovery_module._HeroswebRequestGuard(page)  # type: ignore[arg-type]
    with pytest.raises(UnknownPageStateError, match="did not pass through"):
        episode_guard.require_navigation(episode_url)
    with pytest.raises(DiscoveryIncompleteError, match="did not pass through"):
        discovery_guard.require_navigation(f"https://heros-web.com/series/{WORK_ID}")


async def test_herosweb_failure_metadata_keeps_only_sanitized_route_state() -> None:
    target_url = f"https://heros-web.com/episodes/{'a' * 13}"
    adapter = HeroswebAdapter()
    guard = HeroswebEpisodeRouteGuard(object(), episode_id="a" * 13)  # type: ignore[arg-type]
    guard.main_frame_navigation_urls.append(target_url)
    guard.last_main_frame_response_status = 302
    guard.navigation_violation = "GET heros-web.com/episodes/aaaaaaaaaaaaa redirect 302"
    guard.main_frame_error_category = "http_redirect"
    adapter._route_guard = guard

    metadata = await adapter.collect_debug_metadata(object())  # type: ignore[arg-type]
    route = metadata["main_document_route"]
    assert route == {
        "interception_count": 1,
        "last_url": target_url,
        "response_status": 302,
        "navigation_violation": guard.navigation_violation,
        "navigation_frame_role": None,
        "error_category": "http_redirect",
        "current_page_service_worker_controlled": None,
    }
    assert metadata["blocked_external_writes"] == {
        "count": 0,
        "host_paths": [],
    }
    assert "cookie" not in json.dumps(metadata).lower()


async def test_herosweb_external_post_navigation_is_fatal_before_write_policy() -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        url = "https://analytics.example/navigation"
        method = "POST"
        frame = FakePage.main_frame

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.aborted = False
            self.fallback_called = False

        async def abort(self) -> None:
            self.aborted = True

        async def fallback(self) -> None:
            self.fallback_called = True

    guard = HeroswebEpisodeRouteGuard(
        FakePage(), episode_id="a" * 13  # type: ignore[arg-type]
    )
    route = FakeRoute()
    await guard(route)

    assert route.aborted is True
    assert route.fallback_called is False
    assert guard.blocked_external_writes == []
    assert guard.navigation_frame_role == "main_frame"
    with pytest.raises(UnknownPageStateError, match="unapproved navigation"):
        guard.raise_if_failed()


@pytest.mark.parametrize(
    (
        "url",
        "frame_role",
        "fatal",
        "expected_external_writes",
        "expected_unexpected_write",
    ),
    [
        (
            "https://analytics.example/iframe-submit",
            "subframe",
            False,
            ["analytics.example/iframe-submit"],
            None,
        ),
        (
            "https://comicsviewer.heros-web.com/api/unapproved",
            "subframe",
            True,
            [],
            "comicsviewer.heros-web.com/api/unapproved",
        ),
        (
            "https://analytics.example/unknown-frame",
            "unknown",
            True,
            [],
            None,
        ),
    ],
)
async def test_herosweb_non_get_navigation_records_frame_role_and_fails_closed(
    url: str,
    frame_role: str,
    fatal: bool,
    expected_external_writes: list[str],
    expected_unexpected_write: str | None,
) -> None:
    class FakePage:
        main_frame = object()

    class FakeRequest:
        method = "POST"

        def __init__(self) -> None:
            self.url = url

        @property
        def frame(self):
            if frame_role == "unknown":
                raise PlaywrightError("synthetic frame unavailable")
            if frame_role == "main_frame":
                return FakePage.main_frame
            return object()

        @staticmethod
        def is_navigation_request() -> bool:
            return True

    class FakeRoute:
        request = FakeRequest()

        def __init__(self) -> None:
            self.aborted = False
            self.fallback_called = False

        async def abort(self) -> None:
            self.aborted = True

        async def fallback(self) -> None:
            self.fallback_called = True

    guard = HeroswebEpisodeRouteGuard(
        FakePage(), episode_id="a" * 13  # type: ignore[arg-type]
    )
    route = FakeRoute()
    await guard(route)

    assert route.aborted is True
    assert route.fallback_called is False
    assert guard.navigation_frame_role == frame_role
    assert guard.blocked_external_writes == expected_external_writes
    assert guard.unexpected_write == expected_unexpected_write
    if fatal:
        with pytest.raises(UnknownPageStateError):
            guard.raise_if_failed()
    else:
        guard.raise_if_failed()


def _authenticated_root(*, width: float, height: float, rows: list[dict[str, object]], mirror: bool = False):
    return {
        "classTokens": ["mode-last", "series-eplist-default"],
        "parentChain": [
            {"tag": "DIV", "classTokens": ["series-eplist"] if mirror else
             ["mode-has-eps", "mode-user", "series-eplist"]},
            {"tag": "DIV", "classTokens": ["series-eplist-main"]},
        ],
        "insideMain": True,
        "hidden": False,
        "inert": False,
        "ariaHidden": None,
        "styleChain": [
            {"display": "block", "visibility": "visible", "opacity": "1"},
            {"display": "none" if mirror else "block", "visibility": "visible", "opacity": "1"},
            {"display": "block", "visibility": "visible", "opacity": "1"},
        ],
        "width": width,
        "height": height,
        "directRowCount": len(rows),
        "nestedRowCount": len(rows),
        "rows": rows,
    }


def _snapshot_row(
    *, date: str = "2026/05/18", access_text: str = "無料", access_label: str = "無料"
) -> dict[str, object]:
    return {
        "linkCount": 1,
        "href": "https://heros-web.com/episodes/0000000000001",
        "titleCount": 1,
        "title": "Episode 1",
        "dateCount": 1,
        "date": date,
        "accessCount": 1,
        "accessText": access_text,
        "accessChildren": _free_access_children(access_label),
        "freeLabels": [{"text": access_label, "modeFree": True}],
        "paidParents": [],
        "paidItems": [],
        "quotaIcons": [],
    }


def _authenticated_snapshot(*roots: dict[str, object]) -> dict[str, object]:
    return {
        "canonicalCount": 1,
        "canonicals": [f"{BASE}/3"],
        "mainCount": 1,
        "rootCount": len(roots),
        "documentRootCount": len(roots),
        "rangeContainerCount": 1,
        "allRowCount": sum(root["nestedRowCount"] for root in roots),
        "rootRowCount": sum(root["nestedRowCount"] for root in roots),
        "titles": ["Fixture Work"],
        "rangeLinks": [{"label": "61-87", "href": f"{BASE}/3", "class": "mode-current"}],
        "roots": list(roots),
    }


@pytest.mark.parametrize("rented", [False, True])
def test_herosweb_authenticated_root_mirror_requires_exact_current_owner_and_records(rented) -> None:
    row = _rental_row() if rented else _snapshot_row()
    public_row = {
        **_snapshot_row(), "accessText": "", "freeLabels": [],
        "accessChildren": _quota_access_children(),
        "quotaIcons": [
            {"class": "series-eplist-item-access-icon", "dataE2e": marker}
            for marker in ("eliWfIcon", "eliIfIcon")
        ],
    } if rented else row
    owner = _authenticated_root(width=578, height=2232.6, rows=[row])
    mirror = _authenticated_root(width=0, height=0, rows=[public_row], mirror=True)
    title, rows = _validate_snapshot(
        _authenticated_snapshot(owner, mirror),
        expected_url=f"{BASE}/3",
        work_id=WORK_ID,
        first_position=61,
        authenticated=True,
    )
    assert title == "Fixture Work"
    assert [(item.episode_id, item.global_position, item.access_mode) for item in rows] == [
        ("0000000000001", 61, "quota" if rented else "free")
    ]
    if rented:
        with pytest.raises(DiscoveryIncompleteError, match="mirror diverges"):
            _validate_snapshot(
                _authenticated_snapshot(owner, mirror), expected_url=f"{BASE}/3",
                work_id=WORK_ID, first_position=61, authenticated=False,
            )

    duplicate_rendered = _authenticated_root(width=300, height=400, rows=[row], mirror=True)
    with pytest.raises(DiscoveryIncompleteError, match="owner is not unique"):
        _validate_snapshot(
            _authenticated_snapshot(owner, duplicate_rendered),
            expected_url=f"{BASE}/3", work_id=WORK_ID, first_position=61, authenticated=True,
        )

    divergent = _authenticated_root(
        width=0, height=0, rows=[_snapshot_row(date="2026/05/19")], mirror=True
    )
    with pytest.raises(DiscoveryIncompleteError, match="mirror diverges"):
        _validate_snapshot(
            _authenticated_snapshot(owner, divergent),
            expected_url=f"{BASE}/3", work_id=WORK_ID, first_position=61, authenticated=True,
        )

    malformed_zero = _authenticated_root(width=0, height=20, rows=[row], mirror=True)
    with pytest.raises(DiscoveryIncompleteError, match="malformed zero-area"):
        _validate_snapshot(
            _authenticated_snapshot(owner, malformed_zero),
            expected_url=f"{BASE}/3", work_id=WORK_ID, first_position=61, authenticated=True,
        )


def test_herosweb_root_contract_preserves_anonymous_single_and_gates_now_free() -> None:
    root = _authenticated_root(width=320, height=120, rows=[_snapshot_row()])
    root["parentChain"] = [
        {"tag": "DIV", "classTokens": ["series-eplist"]},
        {"tag": "DIV", "classTokens": ["series-eplist-main"]},
    ]
    snapshot = _authenticated_snapshot(root)
    _, rows = _validate_snapshot(
        snapshot,
        expected_url=f"{BASE}/3",
        work_id=WORK_ID,
        first_position=61,
        authenticated=False,
    )
    assert rows[0].access_mode == "free"

    now_free = _snapshot_row(access_text="今なら無料", access_label="今なら無料")
    logged_in_shape = _authenticated_root(width=578, height=2232, rows=[now_free])
    mirror = _authenticated_root(width=0, height=0, rows=[now_free], mirror=True)
    _, rows = _validate_snapshot(
        _authenticated_snapshot(logged_in_shape, mirror),
        expected_url=f"{BASE}/3",
        work_id=WORK_ID,
        first_position=61,
        authenticated=False,
    )
    assert rows[0].access_mode == "unknown"


def test_herosweb_range_pacing_cannot_be_configured_below_live_observation() -> None:
    assert HeroswebDiscoveryAdapter().range_pacing_ms == 3_200
    with pytest.raises(ValueError):
        HeroswebDiscoveryAdapter(range_pacing_ms=3_199)


@pytest.mark.parametrize(
    ("error_text", "category"),
    [
        ("ETIMEDOUT Cookie: synthetic-secret", "timeout"),
        ("EACCES permission denied", "permission_denied"),
        ("ENETUNREACH network is unreachable", "network_unreachable"),
        ("ECONNREFUSED connection refused", "connection_refused"),
        ("ECONNRESET connection reset", "connection_reset"),
        ("DNS name_not_resolved", "dns"),
        ("TLS certificate failure", "tls"),
        ("unclassified transport error", "other"),
    ],
)
def test_herosweb_route_error_category_is_allowlisted_only(
    error_text: str,
    category: str,
) -> None:
    assert discovery_module._safe_route_error_category(RuntimeError(error_text)) == category
