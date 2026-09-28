import pytest

from screenshot_crawler.core.errors import PageChangeTimeoutError, UnsupportedAccessStrategyError
from screenshot_crawler.core.models import ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    BookWalkerAdapter,
    clean_bookwalker_title,
    is_last_page_counter,
    split_bookwalker_title,
)

PRODUCT_ID = "6de7534d-7022-481d-b2d3-05f03f384454"
PRODUCT_URL = f"https://bookwalker.jp/de{PRODUCT_ID}/"
VIEWER_BASE = "https://viewer.bookwalker.jp/03/21/viewer.html"


@pytest.mark.asyncio
async def test_bookwalker_configure_run_accepts_all_strategies() -> None:
    adapter = BookWalkerAdapter()
    page = object()

    for strategy in ("auto", "direct", "quota"):
        await adapter.configure_run(page, strategy)  # type: ignore[arg-type]
        assert adapter._access_strategy == strategy


@pytest.mark.asyncio
async def test_bookwalker_configure_run_rejects_unknown_strategy() -> None:
    with pytest.raises(UnsupportedAccessStrategyError, match="access_strategy='invalid'"):
        await BookWalkerAdapter().configure_run(object(), "invalid")  # type: ignore[arg-type]


def test_bookwalker_content_id_from_url() -> None:
    url = "https://viewer.bookwalker.jp/03/30/viewer.html?cid=abc-123&cty=0"
    assert BookWalkerAdapter.content_id_from_url(url) == "abc-123"


def test_bookwalker_content_id_from_product_url() -> None:
    url = "https://bookwalker.jp/de6de7534d-7022-481d-b2d3-05f03f384454/"
    assert (
        BookWalkerAdapter.content_id_from_url(url)
        == "6de7534d-7022-481d-b2d3-05f03f384454"
    )


def test_bookwalker_page_counter_parser() -> None:
    assert BookWalkerAdapter.parse_page_counter("3 / 120") == (3, "3 / 120")
    assert BookWalkerAdapter.parse_page_counter("") == (None, None)


def test_bookwalker_last_page_counter() -> None:
    assert is_last_page_counter("59 / 59")
    assert not is_last_page_counter("58 / 59")


@pytest.mark.asyncio
async def test_bookwalker_go_next_uses_arrow_left() -> None:
    class FakeKeyboard:
        def __init__(self) -> None:
            self.pressed: list[str] = []

        async def press(self, key: str) -> None:
            self.pressed.append(key)

    class FakePage:
        def __init__(self) -> None:
            self.keyboard = FakeKeyboard()

    adapter = BookWalkerAdapter()
    page = FakePage()
    armed = False

    async def is_last_page(_page: object) -> bool:
        return False

    async def arm_capture(_page: object) -> None:
        nonlocal armed
        armed = True

    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._arm_native_capture = arm_capture  # type: ignore[method-assign]

    await adapter.go_next(page)  # type: ignore[arg-type]

    assert armed
    assert page.keyboard.pressed == ["ArrowLeft"]


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_uses_click_after_arrow_stalls() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 400
    adapter.advance_retry_count = 1
    adapter.advance_retry_interval_ms = 200
    page = FakePage()
    previous = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    current = previous
    click_count = 0

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return current

    async def is_last_page(_page: object) -> bool:
        return False

    async def render_ready(_page: object) -> None:
        return

    async def click_fallback(_page: object) -> None:
        nonlocal current, click_count
        click_count += 1
        current = ContentIdentity(
            page_id="2/60", page_number=2, source_id="source"
        )

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._wait_for_render_ready = render_ready  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]

    await adapter.wait_for_change(page, previous)  # type: ignore[arg-type]

    assert click_count == 1
    assert current.page_id == "2/60"


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_times_out_after_fallback() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 200
    adapter.advance_retry_count = 1
    adapter.advance_retry_interval_ms = 100
    page = FakePage()
    identity = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    click_count = 0

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return identity

    async def is_last_page(_page: object) -> bool:
        return False

    async def click_fallback(_page: object) -> None:
        nonlocal click_count
        click_count += 1

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]

    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, identity)  # type: ignore[arg-type]

    assert click_count == 1


@pytest.mark.asyncio
async def test_bookwalker_wait_for_change_alternates_click_and_arrow_retries() -> None:
    class FakePage:
        async def wait_for_timeout(self, _milliseconds: int) -> None:
            return

    adapter = BookWalkerAdapter()
    adapter.page_change_timeout_ms = 700
    adapter.advance_retry_count = 3
    adapter.advance_retry_interval_ms = 100
    page = FakePage()
    identity = ContentIdentity(page_id="1/60", page_number=1, source_id="source")
    actions: list[str] = []

    async def detect_state(_page: object) -> PageState:
        return PageState.CONTENT

    async def get_identity(_page: object) -> ContentIdentity:
        return identity

    async def is_last_page(_page: object) -> bool:
        return False

    async def click_fallback(_page: object) -> None:
        actions.append("click")

    async def press_arrow(_page: object) -> None:
        actions.append("arrow")

    adapter.detect_state = detect_state  # type: ignore[method-assign]
    adapter.get_content_identity = get_identity  # type: ignore[method-assign]
    adapter._is_last_page_counter = is_last_page  # type: ignore[method-assign]
    adapter._click_left_edge = click_fallback  # type: ignore[method-assign]
    adapter._press_left_arrow = press_arrow  # type: ignore[method-assign]

    with pytest.raises(PageChangeTimeoutError):
        await adapter.wait_for_change(page, identity)  # type: ignore[arg-type]

    assert actions == ["click", "arrow", "click"]


def test_bookwalker_read_link_score_prefers_owned_reader_over_trial() -> None:
    content_id = "6de7534d-7022-481d-b2d3-05f03f384454"
    trial = {
        "text": "試し読み",
        "action": "trial_reading",
        "href": "https://bookwalker.jp/item/?sample=1",
        "uuid": content_id,
    }
    owned = {
        "text": "読む",
        "action": "reading",
        "href": "https://viewer.bookwalker.jp/03/21/viewer.html?cid=" + content_id,
        "uuid": content_id,
    }

    assert BookWalkerAdapter.score_read_link(owned, content_id) > (
        BookWalkerAdapter.score_read_link(trial, content_id)
    )


def test_bookwalker_read_link_score_recognizes_ten_minute_reading() -> None:
    candidate = {
        "text": "10分まる読み",
        "action": "subscription_reading",
        "href": "https://viewer.bookwalker.jp/viewer.html",
        "uuid": "content-id",
    }

    assert BookWalkerAdapter.score_read_link(candidate, "content-id") >= 260


def test_bookwalker_read_link_candidate_recognizes_actual_japanese_labels() -> None:
    candidate = {
        "text": "10\u5206\u307e\u308b\u8aad\u307f",
        "action": None,
        "href": "",
    }

    assert BookWalkerAdapter.is_read_link_candidate(candidate)


def test_bookwalker_read_link_candidate_excludes_cover_and_check_links() -> None:
    assert not BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "cover", "href": "?sample=1"}
    )
    assert not BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "check", "href": "https://member.bookwalker.jp/"}
    )
    assert BookWalkerAdapter.is_read_link_candidate(
        {"text": "10分まる読み", "action": "subscription_reading", "href": ""}
    )
    assert BookWalkerAdapter.is_read_link_candidate(
        {"text": "", "action": "read_maruyomi", "href": ""}
    )


def test_bookwalker_title_removes_campaign_tag_and_formats_volume() -> None:
    assert clean_bookwalker_title("作品名4【電子特別版】") == "作品名4"
    assert split_bookwalker_title("作品名4【電子特別版】") == ("作品名", "第04巻")


def test_bookwalker_title_uses_three_digits_for_large_series() -> None:
    assert split_bookwalker_title("作品名1", series_count=100) == ("作品名", "第001巻")
    assert split_bookwalker_title("作品名100") == ("作品名", "第100巻")


def test_bookwalker_title_without_volume_is_preserved() -> None:
    assert split_bookwalker_title("作品名【期間限定】") == ("作品名", None)
