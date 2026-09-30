from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from screenshot_crawler import cli
from screenshot_crawler.core.errors import (
    AccessResourceUnavailableError,
    CaptureUnavailableError,
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.zeblack import (
    ZeblackAdapter,
    parse_zeblack_page_alt,
    parse_zeblack_viewer_url,
    validate_zeblack_ticket_control_counts,
)
from screenshot_crawler.site_adapters.zeblack.access import (
    is_zeblack_relevant_host,
)
from screenshot_crawler.site_adapters.zeblack.live_access import ZeblackLiveAccessState
from screenshot_crawler.site_adapters.zeblack.native_capture import (
    capture_zeblack_source_image,
    is_zeblack_blob_response,
    select_zeblack_active_rows,
)

TARGET = "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/9265713/viewer"
BLOB_0 = "blob:https://zebrack-comic.shueisha.co.jp/00000000-0000-0000-0000-000000000000"
BLOB_1 = "blob:https://zebrack-comic.shueisha.co.jp/11111111-1111-1111-1111-111111111111"


def _jpeg(color: tuple[int, int, int], size: tuple[int, int] = (760, 1080)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _webp(color: tuple[int, int, int], size: tuple[int, int] = (760, 1080)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="WEBP", quality=92)
    return buffer.getvalue()


def _row(
    alt: str,
    source: str,
    *,
    dom_order: int = 0,
    x: float = 0,
    in_viewport: bool = True,
    visible: bool = True,
    width: int = 760,
    height: int = 1080,
) -> dict[str, object]:
    return {
        "page_alt": alt,
        "src": source,
        "current_src": source,
        "natural_width": width,
        "natural_height": height,
        "visibility": "visible" if visible else "hidden",
        "visible": visible,
        "in_viewport": in_viewport,
        "dom_order": dom_order,
        "x": x,
        "y": 0,
        "width": 760,
        "height": 1080,
    }


def _patch_rows(monkeypatch, adapter: ZeblackAdapter, page: _FakePage) -> None:
    async def rows(_page: object) -> list[dict[str, object]]:
        return page.rows

    monkeypatch.setattr(adapter, "_dom_rows", rows)


class _FakeLocator:
    def __init__(self, page: _FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    async def evaluate_all(self, _script: str) -> object:
        if self.selector == "img":
            return self.page.rows
        if "iframe" in self.selector:
            return self.page.ad_signal
        if "-KWKsa_spread" in self.selector:
            return self.page.last_page_signal and self.page.last_page_in_viewport
        return self.page.next_signal

    def nth(self, index: int) -> _FakeLocator:
        self.page.nth_calls.append(index)
        return self


class _FakeKeyboard:
    def __init__(self) -> None:
        self.presses: list[str] = []

    async def press(self, key: str) -> None:
        self.presses.append(key)


class _FakePage:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        next_signal: bool = False,
        ad_signal: bool = False,
        last_page_signal: bool = False,
        last_page_in_viewport: bool = True,
    ) -> None:
        self.url = TARGET
        self.rows = rows
        self.next_signal = next_signal
        self.ad_signal = ad_signal
        self.last_page_signal = last_page_signal
        self.last_page_in_viewport = last_page_in_viewport
        self.nth_calls: list[int] = []
        self.keyboard = _FakeKeyboard()
        self.listeners: list[tuple[str, object]] = []
        self.focus: dict[str, object] = {"unsafe": False}

    def locator(self, selector: str) -> _FakeLocator:
        return _FakeLocator(self, selector)

    def on(self, event: str, callback: object) -> None:
        self.listeners.append((event, callback))

    def remove_listener(self, event: str, callback: object) -> None:
        self.listeners = [item for item in self.listeners if item != (event, callback)]

    async def evaluate(self, _script: str) -> object:
        return self.focus

    async def title(self) -> str:
        return "A chapter | ゼブラック"

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return


class _BodyResponse:
    def __init__(self, url: str, body: bytes) -> None:
        self.url = url
        self._body = body

    async def body(self) -> bytes:
        return self._body


def test_strict_viewer_url_parse_and_page_alt_parse() -> None:
    assert parse_zeblack_viewer_url(TARGET) == parse_zeblack_viewer_url(
        TARGET + "?from=test#page=2"
    )
    assert parse_zeblack_viewer_url(TARGET).title_id == "118286"  # type: ignore[union-attr]
    assert parse_zeblack_viewer_url(TARGET.replace("zebrack-comic", "example")) is None
    assert parse_zeblack_viewer_url(TARGET.replace("/viewer", "")) is None
    assert parse_zeblack_viewer_url(TARGET.replace("118286", "title-id")) is None
    assert parse_zeblack_viewer_url(TARGET.replace("https://", "http://")) is None
    assert parse_zeblack_page_alt("page_0") == 0
    assert parse_zeblack_page_alt("page_12") == 12
    assert parse_zeblack_page_alt("page_1_extra") is None
    assert parse_zeblack_page_alt("page_") is None


@pytest.mark.asyncio
async def test_initial_navigation_keeps_viewer_target_and_enters_quota_via_chapter_list() -> None:
    adapter = ZeblackAdapter()
    await adapter.configure_run(object(), "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(object(), "work_ticket")  # type: ignore[arg-type]

    assert adapter.resolve_initial_navigation_url(TARGET) == (
        "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/list"
    )
    assert adapter._target_url == TARGET
    assert adapter._target_viewer == parse_zeblack_viewer_url(TARGET)

    await adapter.configure_run(object(), "direct")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(object(), None)  # type: ignore[arg-type]
    assert adapter.resolve_initial_navigation_url(TARGET) == TARGET


@pytest.mark.asyncio
async def test_quota_initial_navigation_fails_closed_for_invalid_viewer_target() -> None:
    adapter = ZeblackAdapter()
    await adapter.configure_run(object(), "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(object(), "work_ticket")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="strict viewer"):
        adapter.resolve_initial_navigation_url(
            "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/list"
        )


def test_registry_and_minimal_access_profile() -> None:
    assert isinstance(cli._registry().create("zeblack"), ZeblackAdapter)
    assert "zeblack" in cli._discovery_registry().sites()
    assert "zeblack" in cli._batch_policy_registry().sites()
    assert is_zeblack_relevant_host("https://zebrack-comic.shueisha.co.jp/page")
    assert is_zeblack_relevant_host("https://api2.zebrack-comic.com/api/v3/title_chapter_list")
    assert is_zeblack_relevant_host("https://asset.zebrack-comic.com/page")
    assert is_zeblack_relevant_host(BLOB_0)
    assert not is_zeblack_relevant_host("https://example.test/page")


def test_active_rows_are_numeric_and_fail_closed() -> None:
    rows = select_zeblack_active_rows(
        [_row("page_2", BLOB_1, dom_order=0, x=0), _row("page_1", BLOB_0, dom_order=1, x=900)]
    )
    assert [row["page_index"] for row in rows] == [1, 2]
    assert [row["dom_order"] for row in rows] == [1, 0]
    assert select_zeblack_active_rows(
        [_row("page_0", BLOB_0, in_viewport=False)]
    ) == []
    with pytest.raises(ValueError, match="Duplicate"):
        select_zeblack_active_rows([_row("page_1", BLOB_0), _row("page_1", BLOB_1)])
    with pytest.raises(ValueError, match="no Zeblack blob"):
        select_zeblack_active_rows([_row("page_0", "https://asset.zebrack-comic.com/x")])
    with pytest.raises(ValueError, match="Malformed"):
        select_zeblack_active_rows([_row("page_bad", BLOB_0)])


def test_blob_response_filter_excludes_asset_and_unrelated_blob() -> None:
    assert is_zeblack_blob_response(SimpleNamespace(url=BLOB_0))
    assert not is_zeblack_blob_response(
        SimpleNamespace(url="https://asset.zebrack-comic.com/page.jpg")
    )
    assert not is_zeblack_blob_response(
        SimpleNamespace(url="blob:https://example.test/00000000")
    )


@pytest.mark.asyncio
async def test_access_strategy_and_quota_resource_contract() -> None:
    adapter = ZeblackAdapter()
    await adapter.configure_run(object(), "auto")  # type: ignore[arg-type]
    await adapter.configure_run(object(), "direct")  # type: ignore[arg-type]
    await adapter.configure_run(object(), "quota")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(object(), None)  # type: ignore[arg-type]
    await adapter.configure_quota_resource(object(), "work_ticket")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(object(), "ticket")  # type: ignore[arg-type]
    await adapter.configure_run(object(), "direct")  # type: ignore[arg-type]
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter.configure_quota_resource(object(), "work_ticket")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("ticket_count", "point_count", "coin_count"),
    [(0, 0, 0), (2, 0, 0), (1, 1, 0), (1, 0, 1)],
)
def test_ticket_only_control_is_fail_closed(
    ticket_count: int, point_count: int, coin_count: int
) -> None:
    with pytest.raises(UnsupportedAccessStrategyError):
        validate_zeblack_ticket_control_counts(
            ticket_count,
            point_count=point_count,
            coin_count=coin_count,
        )


class _TicketLocator:
    def __init__(self, page: _TicketPage, text: str) -> None:
        self.page = page
        self.text = text

    async def count(self) -> int:
        return self.page.counts.get(self.text, 0)

    def nth(self, _index: int) -> _TicketLocator:
        return self

    async def is_visible(self) -> bool:
        return True

    async def is_enabled(self) -> bool:
        return True

    async def evaluate(self, _script: str) -> str:
        return "div"

    async def click(self, **_kwargs: object) -> None:
        self.page.clicks += 1
        if self.page.click_navigate_to is not None:
            self.page.url = self.page.click_navigate_to


class _TicketPage:
    def __init__(
        self,
        counts: dict[str, int],
        *,
        url: str = TARGET,
        click_navigate_to: str | None = None,
    ) -> None:
        self.counts = counts
        self.clicks = 0
        self.url = url
        self.click_navigate_to = click_navigate_to

    def get_by_text(self, text: str, *, exact: bool) -> _TicketLocator:
        assert exact is True
        return _TicketLocator(self, text)

    def locator(self, _selector: str) -> _TicketLocator:
        return _TicketLocator(self, "__dialog__")

    async def goto(self, url: str, **_kwargs: object) -> None:
        self.url = url

    async def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


@pytest.mark.asyncio
async def test_ticket_click_is_confirmed_once_and_never_retried(monkeypatch) -> None:
    chapter_list = "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/list"
    page = _TicketPage(
        {"チケットを使って読む": 1},
        url=chapter_list,
        click_navigate_to=TARGET,
    )
    adapter = ZeblackAdapter()
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    adapter._live_access = ZeblackLiveAccessState(
        title_id="118286",
        chapter_id="9265713",
        target_main_name="第25話 プロの実力",
        status_value=2,
        status_name="TICKET_AVAILABLE",
        ticket_available_ids=("9265713",),
    )

    async def stable_content(_page: object) -> None:
        return None

    monkeypatch.setattr(adapter, "_wait_for_initial_content", stable_content)
    await adapter._enter_with_work_ticket(page)  # type: ignore[arg-type]

    consumption = adapter.get_access_consumption()
    assert page.clicks == 1
    assert consumption.consumed is True
    assert consumption.resource == "work_ticket"
    assert consumption.consumed_at is not None
    assert consumption.consumed_at.tzinfo is not None
    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._enter_with_work_ticket(page)  # type: ignore[arg-type]
    assert page.clicks == 1


@pytest.mark.asyncio
async def test_point_entry_control_is_rejected_without_click() -> None:
    page = _TicketPage({"ポイントを使って読む": 1})
    adapter = ZeblackAdapter()

    with pytest.raises(UnsupportedAccessStrategyError):
        await adapter._wait_for_ticket_control(page)  # type: ignore[arg-type]

    assert page.clicks == 0


def _live_state(status_value: int, ticket_available_ids: tuple[str, ...]) -> ZeblackLiveAccessState:
    names = {
        0: "FREE",
        1: "RENTAL",
        2: "TICKET_AVAILABLE",
        3: "TICKET_UNAVAILABLE",
        4: "POINT",
        5: "COIN",
        6: "TICKET_UNAVAILABLE_COIN_ONLY",
    }
    return ZeblackLiveAccessState(
        title_id="118286",
        chapter_id="9265713",
        target_main_name="第25話 プロの実力",
        status_value=status_value,
        status_name=names.get(status_value, "UNKNOWN"),
        ticket_available_ids=ticket_available_ids,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "ticket_ids", "reason", "stop"),
    [
        (4, ("9265714",), "work_ticket_not_available_for_chapter", False),
        (4, (), "work_ticket_unavailable", True),
        (3, ("9265714",), "work_ticket_not_available_for_chapter", False),
        (5, (), "work_ticket_unavailable", True),
    ],
)
async def test_quota_live_state_skips_unavailable_without_click(
    monkeypatch,
    status: int,
    ticket_ids: tuple[str, ...],
    reason: str,
    stop: bool,
) -> None:
    page = _TicketPage({})
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(page, "work_ticket")  # type: ignore[arg-type]
    adapter._target_url = TARGET
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    monkeypatch.setattr(adapter, "_has_preexisting_content", lambda _page: _false())

    async def ready(_page: object) -> None:
        return None

    monkeypatch.setattr(adapter, "_wait_for_viewer_ready", ready)

    async def observe(_page: object, **_kwargs: object) -> ZeblackLiveAccessState:
        return _live_state(status, ticket_ids)

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter._initialize_quota_entry(page, entry_only=False)  # type: ignore[arg-type]
    assert error.value.reason == reason
    assert error.value.stop_resource_pass is stop
    assert page.clicks == 0
    assert adapter.get_access_consumption().consumed is False


@pytest.mark.asyncio
async def test_ticket_available_status_wins_over_preexisting_page_placeholders(
    monkeypatch,
) -> None:
    chapter_list = "https://zebrack-comic.shueisha.co.jp/title/118286/chapter/list"
    page = _TicketPage({}, url=chapter_list)
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(page, "work_ticket")  # type: ignore[arg-type]
    adapter._target_url = TARGET
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)

    async def observe(_page: object, **_kwargs: object) -> ZeblackLiveAccessState:
        return _live_state(2, ("9265713",))

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )

    calls: list[str] = []

    async def click(_page: object) -> object:
        calls.append("chapter")
        return object()

    async def enter(_page: object, *, modal_scope: object) -> None:
        del modal_scope
        calls.append("ticket")

    monkeypatch.setattr(adapter, "_click_target_chapter", click)
    monkeypatch.setattr(adapter, "_enter_with_work_ticket", enter)
    await adapter._initialize_quota_entry(page, entry_only=True)  # type: ignore[arg-type]

    assert calls == ["chapter", "ticket"]


@pytest.mark.asyncio
async def test_viewer_ready_waits_for_stable_page_before_live_preflight(monkeypatch) -> None:
    page = _FakePage([_row("page_0", BLOB_0)])
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    calls: list[str] = []

    async def stable(_page: object) -> None:
        calls.append("stable")

    monkeypatch.setattr(adapter, "_wait_for_initial_content", stable)
    await adapter._wait_for_viewer_ready(page)  # type: ignore[arg-type]
    assert calls == ["stable"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gate_text",
    [
        "チケットを使って読む",
        "ポイントを使って読む",
        "アイテムを使って読む",
        "コインを使って読む",
        "コインを購入する",
    ],
)
async def test_viewer_ready_accepts_known_access_gates_without_click(
    monkeypatch, gate_text: str
) -> None:
    page = _TicketPage({gate_text: 1})
    adapter = ZeblackAdapter()

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_safe_active_page_rows", no_rows)
    await adapter._wait_for_viewer_ready(page)  # type: ignore[arg-type]
    assert page.clicks == 0


@pytest.mark.asyncio
async def test_point_gate_reaches_live_preflight_and_skips_without_ticket(
    monkeypatch,
) -> None:
    page = _TicketPage({"ポイントを使って読む": 1})
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(page, "work_ticket")  # type: ignore[arg-type]
    adapter._target_url = TARGET
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)

    async def no_rows(_page: object) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(adapter, "_safe_active_page_rows", no_rows)

    async def observe(_page: object, **_kwargs: object) -> ZeblackLiveAccessState:
        return _live_state(4, ("9265714",))

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    with pytest.raises(AccessResourceUnavailableError) as error:
        await adapter._initialize_quota_entry(page, entry_only=False)  # type: ignore[arg-type]

    assert error.value.reason == "work_ticket_not_available_for_chapter"
    assert error.value.stop_resource_pass is False
    assert page.clicks == 0
    assert adapter.get_access_consumption().consumed is False


async def _false() -> bool:
    return False


async def _true() -> bool:
    return True


@pytest.mark.asyncio
async def test_unknown_quota_live_status_fails_closed(monkeypatch) -> None:
    page = _TicketPage({})
    adapter = ZeblackAdapter()
    await adapter.configure_run(page, "quota")  # type: ignore[arg-type]
    await adapter.configure_quota_resource(page, "work_ticket")  # type: ignore[arg-type]
    adapter._target_url = TARGET
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    monkeypatch.setattr(adapter, "_has_preexisting_content", lambda _page: _false())

    async def ready(_page: object) -> None:
        return None

    monkeypatch.setattr(adapter, "_wait_for_viewer_ready", ready)

    async def observe(_page: object, **_kwargs: object) -> ZeblackLiveAccessState:
        return _live_state(99, ())

    monkeypatch.setattr(
        "screenshot_crawler.site_adapters.zeblack.adapter.observe_zeblack_live_access",
        observe,
    )
    with pytest.raises(UnknownPageStateError, match="unknown"):
        await adapter._initialize_quota_entry(page, entry_only=False)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_direct_jpeg_capture_is_unchanged_and_releases_used_sources(monkeypatch) -> None:
    page = _FakePage([_row("page_1", BLOB_1, dom_order=0), _row("page_0", BLOB_0, dom_order=1)])
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    adapter._handle_source_response(_BodyResponse(BLOB_0, _jpeg((255, 0, 0))))
    adapter._handle_source_response(_BodyResponse(BLOB_1, _jpeg((0, 255, 0))))
    captures = await adapter.capture_page(page)  # type: ignore[arg-type]
    assert captures is not None
    assert [capture.mime_type for capture in captures] == ["image/jpeg", "image/jpeg"]
    assert [capture.file_extension for capture in captures] == [".jpg", ".jpg"]
    assert [capture.width for capture in captures] == [760, 760]
    assert len(adapter._source_response_tasks) == 0
    assert captures[0].data.startswith(b"\xff\xd8\xff")


def test_source_native_webp_capture_is_unchanged() -> None:
    source = _webp((0, 0, 255))
    capture = capture_zeblack_source_image(
        source,
        expected_width=760,
        expected_height=1080,
    )

    assert capture.data == source
    assert capture.mime_type == "image/webp"
    assert capture.file_extension == ".webp"
    assert (capture.width, capture.height) == (760, 1080)


@pytest.mark.asyncio
async def test_direct_capture_supports_mixed_jpeg_and_webp_spread(monkeypatch) -> None:
    page = _FakePage(
        [_row("page_1", BLOB_1, dom_order=0), _row("page_0", BLOB_0, dom_order=1)]
    )
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    jpeg = _jpeg((255, 0, 0))
    webp = _webp((0, 255, 0))
    adapter._handle_source_response(_BodyResponse(BLOB_0, jpeg))
    adapter._handle_source_response(_BodyResponse(BLOB_1, webp))

    captures = await adapter.capture_page(page)  # type: ignore[arg-type]

    assert captures is not None
    assert [capture.mime_type for capture in captures] == ["image/jpeg", "image/webp"]
    assert [capture.file_extension for capture in captures] == [".jpg", ".webp"]
    assert [capture.data for capture in captures] == [jpeg, webp]


def test_source_native_webp_dimension_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        capture_zeblack_source_image(
            _webp((0, 0, 255), size=(100, 100)),
            expected_width=760,
            expected_height=1080,
        )


def test_source_native_corrupt_body_is_rejected() -> None:
    with pytest.raises(ValueError, match="supported decodable image"):
        capture_zeblack_source_image(
            b"not an image",
            expected_width=760,
            expected_height=1080,
        )


@pytest.mark.asyncio
async def test_direct_spread_is_all_or_none_and_fallback_is_numeric(monkeypatch) -> None:
    page = _FakePage([_row("page_1", BLOB_1, dom_order=0), _row("page_0", BLOB_0, dom_order=1)])
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    adapter._handle_source_response(_BodyResponse(BLOB_0, _jpeg((255, 0, 0))))
    with pytest.raises(CaptureUnavailableError):
        await adapter.capture_page(page)  # type: ignore[arg-type]
    targets = await adapter.get_capture_targets(page)  # type: ignore[arg-type]
    assert len(targets) == 2
    assert page.nth_calls[-2:] == [1, 0]
    assert adapter._capture_mode == "locator_fallback"


@pytest.mark.asyncio
async def test_source_cache_is_bounded(monkeypatch) -> None:
    adapter = ZeblackAdapter()
    adapter.max_blob_responses = 2
    for index in range(3):
        url = f"blob:https://zebrack-comic.shueisha.co.jp/{index:08d}"
        adapter._handle_source_response(_BodyResponse(url, _jpeg((index, 0, 0))))
    assert len(adapter._source_response_tasks) == 2
    await adapter._clear_source_cache()


@pytest.mark.asyncio
async def test_content_identity_context_and_state_priority(monkeypatch) -> None:
    page = _FakePage([_row("page_2", BLOB_1, dom_order=0), _row("page_1", BLOB_0, dom_order=1)])
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    identity = await adapter.get_content_identity(page)  # type: ignore[arg-type]
    context = await adapter.get_content_context(page)  # type: ignore[arg-type]
    assert identity.page_id == "page_1+page_2"
    assert identity.page_number == 2
    assert identity.source_id == "9265713"
    assert context.work_id == "118286"
    assert context.chapter_id == "9265713"
    page.next_signal = True
    assert await adapter.detect_state(page) == PageState.CONTENT  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_content_identity_page_number_is_first_logical_page(monkeypatch) -> None:
    page = _FakePage(
        [_row("page_4", BLOB_1, dom_order=0), _row("page_3", BLOB_0, dom_order=1)]
    )
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)

    assert (await adapter.get_content_identity(page)).page_number == 4  # type: ignore[arg-type]

    page.rows = [_row("page_23", BLOB_0)]
    assert (await adapter.get_content_identity(page)).page_number == 24  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_terminal_requires_stable_transition_and_visible_control(monkeypatch) -> None:
    page = _FakePage([], next_signal=True)
    adapter = ZeblackAdapter()
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    _patch_rows(monkeypatch, adapter, page)
    assert await adapter.detect_state(page) == PageState.UNKNOWN  # type: ignore[arg-type]
    adapter._transition_stable = True
    adapter._transition_kind = "terminal_next_content"
    assert await adapter.detect_state(page) == PageState.NEXT_CONTENT  # type: ignore[arg-type]
    page.next_signal = False
    assert await adapter.detect_state(page) == PageState.UNKNOWN  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_visible_advertisement_spread_is_an_intermediate_state(monkeypatch) -> None:
    page = _FakePage([], ad_signal=True)
    adapter = ZeblackAdapter()
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    _patch_rows(monkeypatch, adapter, page)
    adapter._transition_stable = True
    adapter._transition_kind = "advertisement"

    assert await adapter.detect_state(page) == PageState.AD  # type: ignore[arg-type]
    await adapter.go_next(page)  # type: ignore[arg-type]
    assert page.keyboard.presses == ["ArrowLeft"]


@pytest.mark.asyncio
@pytest.mark.parametrize("in_viewport", [False, True])
async def test_last_page_signal_requires_visible_in_viewport_spread(
    monkeypatch, in_viewport: bool
) -> None:
    page = _FakePage(
        [],
        last_page_signal=True,
        last_page_in_viewport=in_viewport,
    )
    adapter = ZeblackAdapter()
    _patch_rows(monkeypatch, adapter, page)

    assert await adapter._last_page_signal(page) is in_viewport  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_changed_chapter_is_next_content_but_foreign_url_is_unknown() -> None:
    adapter = ZeblackAdapter()
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    page = _FakePage([])
    page.url = TARGET.replace("9265713", "9265714")
    assert await adapter.detect_state(page) == PageState.NEXT_CONTENT  # type: ignore[arg-type]
    page.url = "https://example.test/viewer"
    assert await adapter.detect_state(page) == PageState.UNKNOWN  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_go_next_uses_arrow_left_and_blocks_unsafe_focus(monkeypatch) -> None:
    page = _FakePage([_row("page_0", BLOB_0)])
    adapter = ZeblackAdapter()
    adapter._target_viewer = parse_zeblack_viewer_url(TARGET)
    _patch_rows(monkeypatch, adapter, page)
    await adapter.go_next(page)  # type: ignore[arg-type]
    assert page.keyboard.presses == ["ArrowLeft"]
    page2 = _FakePage([_row("page_0", BLOB_0)])
    page2.focus = {"unsafe": True}
    adapter2 = ZeblackAdapter()
    adapter2._target_viewer = parse_zeblack_viewer_url(TARGET)
    _patch_rows(monkeypatch, adapter2, page2)
    with pytest.raises(PageChangeTimeoutError):
        await adapter2.go_next(page2)  # type: ignore[arg-type]
    assert page2.keyboard.presses == []


@pytest.mark.asyncio
async def test_wait_for_change_requires_changed_and_stable(monkeypatch) -> None:
    page = _FakePage([])
    adapter = ZeblackAdapter()
    adapter._transition_before_signature = ("before",)
    previous = ContentIdentity(page_id="page_0", page_number=1, source_id="9265713")
    row = _row("page_1", BLOB_1)
    snapshots = [
        {"fingerprint": ("after",), "viewer": parse_zeblack_viewer_url(TARGET), "rows": [row], "page_id": "page_1", "terminal_signal": False},
        {"fingerprint": ("after",), "viewer": parse_zeblack_viewer_url(TARGET), "rows": [row], "page_id": "page_1", "terminal_signal": False},
    ]

    async def snapshot(_page: object) -> dict[str, object]:
        return snapshots.pop(0)

    monkeypatch.setattr(adapter, "_snapshot", snapshot)
    await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]
    assert adapter._transition_stable
    assert adapter._transition_kind == "content"


@pytest.mark.asyncio
async def test_wait_for_change_accepts_a_stable_advertisement_spread(monkeypatch) -> None:
    page = _FakePage([])
    adapter = ZeblackAdapter()
    adapter._transition_before_signature = ("before",)
    previous = ContentIdentity(page_id="page_0", page_number=1, source_id="9265713")
    snapshot = {
        "fingerprint": ("ad",),
        "viewer": parse_zeblack_viewer_url(TARGET),
        "rows": [],
        "page_id": None,
        "terminal_signal": False,
        "advertisement_signal": True,
    }

    async def ad_snapshot(_page: object) -> dict[str, object]:
        return snapshot

    monkeypatch.setattr(adapter, "_snapshot", ad_snapshot)
    await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]
    assert adapter._transition_stable
    assert adapter._transition_kind == "advertisement"


@pytest.mark.asyncio
async def test_wait_for_change_no_change_times_out(monkeypatch) -> None:
    page = _FakePage([])
    adapter = ZeblackAdapter()
    adapter.page_change_timeout_ms = 200
    adapter._transition_before_signature = ("before",)
    previous = ContentIdentity(page_id="page_0", page_number=1, source_id="9265713")
    snapshot = {
        "fingerprint": ("before",),
        "viewer": parse_zeblack_viewer_url(TARGET),
        "rows": [],
        "page_id": None,
        "terminal_signal": False,
    }
    async def unchanged_snapshot(_page: object) -> dict[str, object]:
        return snapshot

    monkeypatch.setattr(adapter, "_snapshot", unchanged_snapshot)
    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]
