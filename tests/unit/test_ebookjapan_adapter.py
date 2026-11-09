from __future__ import annotations

import asyncio
import copy
from collections.abc import Mapping

import pytest

from screenshot_crawler.core.errors import UnknownPageStateError
from screenshot_crawler.site_adapters.ebookjapan.adapter import (
    EbookJapanAdapter,
    parse_ebookjapan_product_url,
)
from screenshot_crawler.site_adapters.ebookjapan.viewer import (
    normalize_title,
    parse_page_counter,
    reader_title_matches_owned_title,
)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ({"nodeType": 1, "nodeName": "DIV", "localName": "div", "nodeValue": ""}, False),
        (
            {
                "nodeType": 1,
                "nodeName": "DIV",
                "localName": "div",
                "nodeValue": "",
                "childNodeCount": 0,
            },
            True,
        ),
        (
            {
                "nodeType": 1,
                "nodeName": "DIV",
                "localName": "div",
                "nodeValue": "",
                "childNodeCount": 1,
            },
            False,
        ),
        (
            {
                "nodeType": 1,
                "nodeName": "DIV",
                "localName": "div",
                "nodeValue": "",
                "childNodeCount": 1,
                "children": [{"nodeType": 3, "nodeName": "#text", "nodeValue": "text"}],
            },
            True,
        ),
        (
            {
                "nodeType": 1,
                "nodeName": "DIV",
                "localName": "div",
                "nodeValue": "",
                "childNodeCount": 0,
                "children": [],
            },
            True,
        ),
        ({"nodeType": 3, "nodeName": "#text", "nodeValue": "text"}, True),
    ],
)
def test_cdp_tree_requires_explicit_element_child_count(
    node: dict[str, object], expected: bool
) -> None:
    assert EbookJapanAdapter._cdp_light_tree_is_complete_and_shadow_free(node) is expected


def _observed_angel_terminal_frame() -> dict[str, object]:
    partition = {
        "review": 1,
        "coupon": 1,
        "lottery": 1,
        "recommendAuthor": 4,
        "recommendI2i": 3,
        "header": 3,
    }
    return {
        "status": "end",
        "routeStable": True,
        "slotCount": 287,
        "parts": [],
        "visibleSlots": [],
        "visibleActions": sum(partition.values()),
        "counterVisible": True,
        "deadEnd": [{"visible": True, "textExact": True, "controls": 0, "rect": {"viewport": True}}],
        "terminal": {
            "profile": "angel-dead-end-observed-controls",
            "variant": "lottery-plus-native-header-v1",
            "rootCount": 1,
            "innerCount": 1,
            "rootVisible": True,
            "innerVisible": True,
            "rootInViewport": True,
            "innerInViewport": True,
            "insidePinnedLayout": True,
            "shellChainValid": True,
            "visibleSlotCount": 0,
            "visiblePageCanvasCount": 0,
            "modalCount": 0,
            "actionInventoryCapped": False,
            "actionPartitionComplete": True,
            "unknownActionCount": 0,
            "visibleActionCount": sum(partition.values()),
            "nativeCounterVisible": True,
            "nativeCounter": {"current": 287, "total": 287},
            "markerCount": 1,
            "markerInsideInner": True,
            "markerVisible": True,
            "markerTextExact": True,
            "markerControls": 0,
            "riskyActionCount": 0,
            "moduleCounts": {"review": 1, "coupon": 1, "author": 1, "i2i": 1, "newArrival": 0},
            "newArrivalShapeValid": True,
            "lotteryButtonCount": 1,
            "headerRootCount": 1,
            "headerBarCount": 1,
            "headerMenuCount": 1,
            "headerCounts": {"close-button": 1, "contents-button": 1, "settings-button": 1},
            "partition": partition,
        },
    }


def _legacy_angel_terminal_frame() -> dict[str, object]:
    frame = _observed_angel_terminal_frame()
    partition = {
        "review": 1,
        "coupon": 1,
        "recommendAuthor": 4,
        "recommendI2i": 3,
    }
    frame["visibleActions"] = sum(partition.values())
    terminal = frame["terminal"]
    terminal.update(
        profile="angel-dead-end",
        variant="line-coupon-only-v1",
        visibleActionCount=sum(partition.values()),
        lotteryButtonCount=0,
        headerRootCount=0,
        headerBarCount=0,
        headerMenuCount=0,
        headerCounts={"close-button": 0, "contents-button": 0, "settings-button": 0},
        partition=partition,
    )
    return frame


def test_observed_angel_end_requires_exact_lottery_and_scoped_header_partition() -> None:
    frame = _observed_angel_terminal_frame()
    assert EbookJapanAdapter._is_verified_end_frame(frame, total=287) is True

    for mutation in (
        lambda terminal: terminal.update(lotteryButtonCount=2),
        lambda terminal: terminal.update(headerRootCount=2),
        lambda terminal: terminal.update(headerBarCount=2),
        lambda terminal: terminal.update(headerMenuCount=2),
        lambda terminal: terminal["headerCounts"].update({"settings-button": 2}),
        lambda terminal: terminal["partition"].update(header=2),
        lambda terminal: terminal["partition"].update(unclassified=1),
        lambda terminal: terminal.update(variant="line-coupon-only-v1"),
        lambda terminal: terminal["moduleCounts"].update(extra=1),
    ):
        forged = copy.deepcopy(frame)
        mutation(forged["terminal"])
        assert EbookJapanAdapter._is_verified_end_frame(forged, total=287) is False


@pytest.mark.parametrize("frame_factory", [_legacy_angel_terminal_frame, _observed_angel_terminal_frame])
def test_angel_end_accepts_only_absent_or_exact_new_arrival_shape_and_partition(frame_factory) -> None:
    frame = frame_factory()
    assert EbookJapanAdapter._is_verified_end_frame(frame, total=287) is True

    with_new_arrival = copy.deepcopy(frame)
    with_new_arrival["terminal"]["moduleCounts"]["newArrival"] = 1
    with_new_arrival["terminal"]["partition"]["recommendNewArrival"] = 2
    with_new_arrival["visibleActions"] += 2
    with_new_arrival["terminal"]["visibleActionCount"] += 2
    assert EbookJapanAdapter._is_verified_end_frame(with_new_arrival, total=287) is True

    def add_partition_action(item: dict[str, object], count: int) -> None:
        item["terminal"]["partition"]["recommendNewArrival"] = count
        item["visibleActions"] += count
        item["terminal"]["visibleActionCount"] += count

    mutations = (
        lambda item: item["terminal"]["moduleCounts"].update(newArrival=True),
        lambda item: item["terminal"]["moduleCounts"].update(newArrival=2),
        lambda item: item["terminal"].update(newArrivalShapeValid=False),
        lambda item: item["terminal"]["moduleCounts"].update(newArrival=1),
        lambda item: add_partition_action(item, 2),
        lambda item: item["terminal"]["partition"].update(recommendNewArrival=0),
    )
    for mutation in mutations:
        forged = copy.deepcopy(frame)
        mutation(forged)
        assert EbookJapanAdapter._is_verified_end_frame(forged, total=287) is False

    for count in (1, 3):
        forged = copy.deepcopy(with_new_arrival)
        forged["terminal"]["partition"]["recommendNewArrival"] = count
        delta = count - 2
        forged["visibleActions"] += delta
        forged["terminal"]["visibleActionCount"] += delta
        assert EbookJapanAdapter._is_verified_end_frame(forged, total=287) is False


def _observed_muda_terminal_frame() -> dict[str, object]:
    partition = {
        "review": 1,
        "nextItem": 1,
        "cta": 1,
        "banner": 2,
        "matildaBanner": 1,
        "i2i": 1,
        "author": 2,
        "forYou": 1,
        "header": 3,
    }
    return {
        "status": "end",
        "routeStable": True,
        "slotCount": 193,
        "parts": [],
        "visibleSlots": [],
        "visibleActions": sum(partition.values()),
        "counterVisible": False,
        "deadEnd": [],
        "terminal": {
            "profile": "muda-book-last",
            "rootCount": 1,
            "innerCount": 1,
            "rootVisible": True,
            "innerVisible": True,
            "rootInViewport": True,
            "innerInViewport": True,
            "insidePinnedLayout": True,
            "viewerIdentityValid": True,
            "shellChainValid": True,
            "visibleSlotCount": 0,
            "visiblePageCanvasCount": 0,
            "modalCount": 0,
            "actionInventoryCapped": False,
            "actionPartitionComplete": True,
            "unknownActionCount": 0,
            "unknownOutsideKnownRegionCount": 0,
            "unknownActionScopeKnown": True,
            "visibleActionCount": sum(partition.values()),
            "nativeCounterVisible": False,
            "nativeCounter": None,
            "moduleCounts": {
                "review": 1, "nextItem": 1, "cta": 1, "banner": 1,
                "i2i": 1, "author": 1, "forYou": 1,
            },
            "moduleChildCount": 7,
            "headerRootCount": 1,
            "headerGlobalCount": 1,
            "headerBarCount": 1,
            "headerMenuCount": 1,
            "headerCounts": {"close-button": 1, "contents-button": 1, "settings-button": 1},
            "riskyActionCount": 0,
            "partition": partition,
        },
    }


def test_muda_end_requires_pinned_layout_full_header_and_observed_matilda_action() -> None:
    frame = _observed_muda_terminal_frame()
    assert EbookJapanAdapter._is_verified_end_frame(frame, total=193) is True

    for mutation in (
        lambda terminal: terminal["partition"].update(matildaBanner=2),
        lambda terminal: terminal["partition"].update(nextItem=0),
        lambda terminal: terminal["partition"].update(header=2),
        lambda terminal: terminal.update(headerRootCount=0),
        lambda terminal: terminal.update(headerGlobalCount=2),
        lambda terminal: terminal.update(headerCounts={"close-button": 1, "contents-button": 1, "settings-button": 0}),
        lambda terminal: terminal.update(viewerIdentityValid=False),
        lambda terminal: terminal.update(unknownOutsideKnownRegionCount=1),
    ):
        forged = copy.deepcopy(frame)
        mutation(forged["terminal"])
        forged["visibleActions"] = sum(forged["terminal"]["partition"].values())
        forged["terminal"]["visibleActionCount"] = forged["visibleActions"]
        assert EbookJapanAdapter._is_verified_end_frame(forged, total=193) is False


def _observed_angel_unknown_terminal_frame() -> dict[str, object]:
    frame = _observed_angel_terminal_frame()
    terminal = frame["terminal"]
    frame["status"] = "unknown-terminal-marker"
    frame["counterVisible"] = False
    terminal["nativeCounterVisible"] = False
    terminal["nativeCounter"] = None
    terminal["unknownActionCount"] = 1
    terminal["unknownActionScopeKnown"] = True
    terminal["unknownOutsideKnownRegionCount"] = 0
    terminal["actionPartitionComplete"] = False
    return frame


def test_unknown_angel_terminal_wait_requires_complete_scoped_marker_and_safe_frame() -> None:
    frame = _observed_angel_unknown_terminal_frame()
    assert EbookJapanAdapter._is_waitable_angel_terminal_unknown(frame, total=287) is True

    for mutation in (
        lambda item: item["terminal"].update(unknownOutsideKnownRegionCount=1),
        lambda item: item["terminal"].update(unknownActionScopeKnown=False),
        lambda item: item["terminal"].update(modalCount=1),
        lambda item: item["terminal"].update(actionInventoryCapped=True),
        lambda item: item["terminal"].update(rootInViewport=False),
        lambda item: item["terminal"].update(shellChainValid=False),
        lambda item: item["terminal"].update(markerTextExact=False),
        lambda item: item.update(counterVisible=True),
        lambda item: item.update(visibleSlots=[1]),
        lambda item: item.update(parts=[{}]),
        lambda item: item.update(slotCount=286),
        lambda item: item.update(status="end"),
    ):
        forged = copy.deepcopy(frame)
        mutation(forged)
        assert EbookJapanAdapter._is_waitable_angel_terminal_unknown(forged, total=287) is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "coverage_complete"),
    [
        ("coverage", False),
        ("capture-binding", True),
        ("outside-action", True),
        ("modal", True),
        ("document", True),
        ("slots", True),
        ("layout", True),
        ("observer", True),
        ("malformed-end", True),
    ],
)
async def test_unknown_terminal_anomalies_fail_before_another_wait(
    monkeypatch: pytest.MonkeyPatch, failure: str, coverage_complete: bool,
) -> None:
    frame = _observed_angel_unknown_terminal_frame()
    if failure == "outside-action":
        frame["terminal"]["unknownOutsideKnownRegionCount"] = 1
    elif failure == "modal":
        frame["terminal"]["modalCount"] = 1
    elif failure == "document":
        frame["status"] = "identity-mismatch"
    elif failure == "slots":
        frame["status"] = "slot-order-mismatch"
    elif failure == "layout":
        frame["status"] = "layout-mismatch"
    elif failure == "observer":
        frame["status"] = "observer-overflow"
    elif failure == "malformed-end":
        frame["status"] = "end"
        frame["terminal"]["headerCounts"]["settings-button"] = 0
        frame["terminal"]["actionPartitionComplete"] = False

    class Page:
        url = "https://ebookjapan.yahoo.co.jp/viewer/purchased/B123456789012/"

        def __init__(self) -> None:
            self.wait_calls = 0

        async def evaluate(self, _script: str, _arg: object) -> dict[str, object]:
            return frame

        async def wait_for_timeout(self, _milliseconds: int) -> None:
            self.wait_calls += 1

    class PreviousIdentity:
        page_id = "captured-page"

    page = Page()
    adapter = EbookJapanAdapter()
    adapter._reader_path = "/viewer/purchased/B123456789012/"
    adapter._reader_total = 287
    adapter._page = page
    adapter._transition_pending = True
    adapter._transition_before_key = ("captured-frame",)
    adapter._last_capture_node_key = ("captured-frame",)
    adapter._last_capture_page_id = "captured-page"
    if failure == "capture-binding":
        adapter._transition_before_key = ("different-frame",)
    monkeypatch.setattr(adapter, "_capture_coverage_complete", lambda: coverage_complete)

    with pytest.raises(UnknownPageStateError):
        await adapter.wait_for_change(page, PreviousIdentity())

    assert page.wait_calls == 0
    debug = await adapter.collect_debug_metadata(page)
    first_unknown = debug["ebookjapan_terminal_wait"]["first_unknown"]
    assert first_unknown is not None
    assert first_unknown["status"] in {
        "unknown-terminal-marker", "identity-mismatch", "slot-order-mismatch",
        "layout-mismatch", "observer-overflow", "end",
    }


@pytest.mark.asyncio
async def test_terminal_debug_metadata_is_cached_sanitized_and_does_not_read_page() -> None:
    adapter = EbookJapanAdapter()
    frame = _observed_angel_unknown_terminal_frame()
    frame.update(
        {
            "url": "https://private.example/reader?secret=sentinel-url",
            "title": "sentinel-title",
            "actionText": "sentinel-action",
            "privateReaderB": "sentinel-reader-b",
            "sourceBytes": "sentinel-source-bytes",
            "functionSource": "sentinel-function-source",
        }
    )
    frame["terminal"]["privateReaderB"] = "sentinel-terminal-private"
    sample = adapter._safe_terminal_frame_sample(frame, elapsed_ms=14)
    adapter._terminal_diagnostics = {"first_unknown": sample, "last_sample": sample}

    class NeverReadPage:
        url = "https://private.example/sentinel-url"
        title = "sentinel-title"

        async def evaluate(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("collect_debug_metadata must not read a live Page")

    debug = await adapter.collect_debug_metadata(NeverReadPage())
    serialized = str(debug)
    for sentinel in (
        "sentinel-url", "sentinel-title", "sentinel-action", "sentinel-reader-b",
        "sentinel-terminal-private", "sentinel-source-bytes", "sentinel-function-source",
    ):
        assert sentinel not in serialized
    assert debug["ebookjapan_terminal_wait"]["first_unknown"]["status"] == "unknown-terminal-marker"
    assert debug["ebookjapan_terminal_wait"]["first_unknown"]["native_counter"] is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://ebookjapan.yahoo.co.jp/books/134336/A000083590/", ("134336", "A000083590")),
        ("https://ebookjapan.yahoo.co.jp/books/1/A1/", ("1", "A1")),
        ("http://ebookjapan.yahoo.co.jp/books/134336/A000083590/", None),
        ("https://www.ebookjapan.yahoo.co.jp/books/134336/A000083590/", None),
        ("https://ebookjapan.yahoo.co.jp/books/0134336/A000083590/", None),
        ("https://ebookjapan.yahoo.co.jp/books/134336/A000083590", None),
        ("https://ebookjapan.yahoo.co.jp/books/134336/A000083590/?x=1", None),
        ("https://ebookjapan.yahoo.co.jp/books/134336/A000083590/#top", None),
        ("https://ebookjapan.yahoo.co.jp.evil.test/books/134336/A000083590/", None),
    ],
)
def test_product_url_requires_exact_canonical_identity(url: str, expected: object) -> None:
    assert parse_ebookjapan_product_url(url) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1 / 287", (1, 287)),
        (" 148 / 287 ", (148, 287)),
        ("２８７／２８７", None),
        ("0 / 287", None),
        ("288 / 287", None),
        ("1 /", None),
        (None, None),
    ],
)
def test_native_page_counter_parser_is_bounded(value: str | None, expected: object) -> None:
    assert parse_page_counter(value) == expected


def test_title_normalization_only_folds_width_and_whitespace() -> None:
    assert normalize_title(" エンジェル伝説（１０） ") == "エンジェル伝説(10)"


@pytest.mark.parametrize(
    ("owned", "reader", "expected"),
    [
        ("漫画 2巻", "漫画(2)", True),
        (" ＡＢＣ １０巻 ", "ABC(10)", True),
        ("エンジェル伝説（10）", "エンジェル伝説(10)", True),
        ("漫画 2巻", "漫画(3)", False),
        ("漫画(2)", "漫画 2巻", False),
        ("漫画 02巻", "漫画(2)", False),
        ("シリーズ2 10巻", "シリーズ2(10)", False),
        ("シリーズ 1000巻", "シリーズ(1000)", False),
        ("漫画 2巻", "別漫画(2)", False),
    ],
)
def test_reader_title_accepts_only_exact_or_observed_one_way_volume_alias(
    owned: str, reader: str, expected: bool
) -> None:
    assert reader_title_matches_owned_title(owned, reader) is expected


def test_toolbar_shortcut_frame_guard_binds_viewport_nodes_and_paint() -> None:
    frame = {
        "status": "content",
        "routeStable": True,
        "viewport": {"width": 1537, "height": 877},
        "parts": [
            {
                "slotId": 41,
                "canvasId": 42,
                "slotOrdinal": 9,
                "canvasIndex": 0,
                "backingWidth": 934,
                "backingHeight": 1500,
                "cssRect": {"viewport": True, "left": 301.5, "top": 0, "width": 467, "height": 750},
                "drawGeneration": 3,
                "successfulDraws": 3,
                "mutationCount": 7,
                "drawReady": True,
            }
        ],
    }
    adapter = EbookJapanAdapter()
    assert adapter._same_toolbar_reader_frame(frame, copy.deepcopy(frame)) is True

    mutations = (
        lambda value: value["viewport"].update(width=1538),
        lambda value: value["parts"][0].update(slotId=43),
        lambda value: value["parts"][0]["cssRect"].update(left=302),
        lambda value: value["parts"][0].update(drawGeneration=4),
        lambda value: value.update(status="partial"),
        lambda value: value.update(routeStable=False),
    )
    for mutate in mutations:
        changed = copy.deepcopy(frame)
        mutate(changed)
        assert adapter._same_toolbar_reader_frame(frame, changed) is False


@pytest.mark.asyncio
async def test_entry_waits_for_delayed_live_owned_badge_before_returning(monkeypatch) -> None:
    adapter = EbookJapanAdapter()
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    row = {
        "path": "/books/134336/A000083590/",
        "title": "エンジェル伝説（10）",
        "visible": True,
    }

    def snapshot(ownership: str) -> Mapping[str, object]:
        payload = {"pageUrl": "https://ebookjapan.yahoo.co.jp/books/all/134336/", "accountAuthenticated": True}
        return {"payload": payload, "row": row, "title": row["title"], "ownership": ownership}

    states = ["explicitly_not_owned", "unknown", "owned", "owned", "owned"]
    calls = 0

    async def next_snapshot(_page):
        nonlocal calls
        state = states[min(calls, len(states) - 1)]
        calls += 1
        return snapshot(state)

    class Page:
        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    monkeypatch.setattr(adapter, "_owned_listing_snapshot", next_snapshot)
    monkeypatch.setattr("screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_POLL_SECONDS", 0)
    result = await adapter._wait_for_owned_card(Page())

    assert result["ownership"] == "owned"
    assert calls == 5


@pytest.mark.asyncio
async def test_entry_does_not_accept_unsettled_or_transient_not_owned_card(monkeypatch) -> None:
    adapter = EbookJapanAdapter()
    adapter._series_id = "134336"
    adapter._external_id = "A000083590"
    row = {"path": "/books/134336/A000083590/", "title": "エンジェル伝説（10）"}

    async def transient(_page):
        return {
            "payload": {"pageUrl": "https://ebookjapan.yahoo.co.jp/books/all/134336/", "accountAuthenticated": True},
            "row": row,
            "title": row["title"],
            "ownership": "explicitly_not_owned",
        }

    class Page:
        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    monkeypatch.setattr(adapter, "_owned_listing_snapshot", transient)
    monkeypatch.setattr("screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_SETTLE_SECONDS", 0.01)
    monkeypatch.setattr("screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_POLL_SECONDS", 0)

    with pytest.raises(UnknownPageStateError, match="did not settle"):
        await adapter._wait_for_owned_card(Page())


@pytest.mark.asyncio
async def test_entry_waits_for_delayed_signed_in_account_shell(monkeypatch) -> None:
    adapter = EbookJapanAdapter()
    adapter._series_id = "134336"
    states = [False, False, True]

    class Page:
        calls = 0

        async def evaluate(self, _script):
            authenticated = states[min(self.calls, len(states) - 1)]
            self.calls += 1
            return {
                "pageUrl": "https://ebookjapan.yahoo.co.jp/books/all/134336/",
                "pagePath": "/books/all/134336/",
                "pageHost": "ebookjapan.yahoo.co.jp",
                "oldestFirst": True,
                "declaredTotal": 10,
                "accountAuthenticated": authenticated,
            }

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_POLL_SECONDS",
        0,
    )
    page = Page()
    await adapter._wait_for_signed_in_listing(page)
    assert page.calls == 3


@pytest.mark.asyncio
async def test_entry_rejects_account_shell_that_never_hydrates(monkeypatch) -> None:
    adapter = EbookJapanAdapter()
    adapter._series_id = "134336"

    class Page:
        async def evaluate(self, _script):
            return {
                "pageUrl": "https://ebookjapan.yahoo.co.jp/books/all/134336/",
                "pagePath": "/books/all/134336/",
                "pageHost": "ebookjapan.yahoo.co.jp",
                "oldestFirst": True,
                "declaredTotal": 10,
                "accountAuthenticated": False,
            }

        async def wait_for_timeout(self, milliseconds: int) -> None:
            await asyncio.sleep(milliseconds / 1000)

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_SETTLE_SECONDS",
        0.01,
    )
    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.ebookjapan.adapter._OWNERSHIP_POLL_SECONDS",
        0.002,
    )
    with pytest.raises(UnknownPageStateError, match="account shell did not settle"):
        await adapter._wait_for_signed_in_listing(Page())


@pytest.mark.asyncio
async def test_stale_owned_card_is_rejected_before_reader_click(monkeypatch) -> None:
    adapter = EbookJapanAdapter()
    adapter._owned_title = "エンジェル伝説（10）"
    monkeypatch.setattr(
        adapter,
        "_owned_listing_snapshot",
        lambda _page: _async_result(
            {"ownership": "explicitly_not_owned", "title": "エンジェル伝説（10）"}
        ),
    )

    class NeverTouched:
        async def count(self):
            pytest.fail("stale card locator must not be inspected after rights loss")

    with pytest.raises(UnknownPageStateError, match="immediately before Reader entry"):
        await adapter._recheck_target_before_click(
            object(),
            target_path="/books/134336/A000083590/",
            card=NeverTouched(),
            action=NeverTouched(),
        )


@pytest.mark.asyncio
async def test_reader_waits_for_natural_canvas_transfer_after_route_is_pinned() -> None:
    adapter = EbookJapanAdapter()
    adapter._owned_title = "Mudazumo Naki Kaikaku"
    path = "/viewer/purchased/B123456789012/"
    states = [
        {"status": "partial", "routeStable": True, "slotCount": 193},
        {
            "status": "content",
            "routeStable": True,
            "slotCount": 193,
            "counterVisible": True,
            "counter": {"current": 1, "total": 193},
            "title": "Mudazumo Naki Kaikaku",
        },
    ]

    class Page:
        url = f"https://ebookjapan.yahoo.co.jp{path}"

        async def evaluate(self, _script, _arg):
            return states.pop(0)

        async def wait_for_timeout(self, _ms: int) -> None:
            return None

    frame = await adapter._wait_for_content_frame(
        Page(),
        expected_path=path,
        expected_current=1,
        expected_total=193,
    )

    assert frame["status"] == "content"
    assert states == []


@pytest.mark.asyncio
async def test_reader_ready_wait_rejects_route_or_slot_identity_drift() -> None:
    adapter = EbookJapanAdapter()
    path = "/viewer/purchased/B123456789012/"

    class Page:
        url = "https://ebookjapan.yahoo.co.jp/viewer/purchased/B999999999999/"

        async def evaluate(self, _script, _arg):
            return {"status": "identity-mismatch"}

    with pytest.raises(UnknownPageStateError, match="identity-mismatch"):
        await adapter._wait_for_content_frame(
            Page(), expected_path=path, expected_current=1, expected_total=193
        )


async def _async_result(value):
    return value
