from screenshot_crawler.site_adapters.bookwalker.adapter import (
    BookWalkerAdapter,
    clean_bookwalker_title,
    is_last_page_counter,
    split_bookwalker_title,
)


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
