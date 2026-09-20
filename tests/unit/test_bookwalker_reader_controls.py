import pytest

from screenshot_crawler.site_adapters.bookwalker.reader_controls import (
    ReaderControlKind,
    classify_reader_control,
    is_reader_control_candidate,
)


def test_read_maruyomi_action_is_maruyomi() -> None:
    assert classify_reader_control(
        {"text": "", "action": "read_maruyomi", "href": "", "uuid": None}
    ) is ReaderControlKind.MARUYOMI


def test_ten_minute_visible_text_overrides_subscription_action() -> None:
    assert classify_reader_control(
        {
            "text": "10分まる読み",
            "action": "subscription_reading",
            "href": "",
        }
    ) is ReaderControlKind.MARUYOMI


def test_subscription_action_alone_is_not_maruyomi() -> None:
    classification = classify_reader_control(
        {
            "text": "読み放題で読む",
            "action": "subscription_reading",
            "href": "",
        }
    )
    assert classification is ReaderControlKind.SUBSCRIPTION
    assert classification is not ReaderControlKind.MARUYOMI


def test_trial_action_and_label_are_trial() -> None:
    assert classify_reader_control(
        {"text": "試し読み", "action": "trial_reading", "href": ""}
    ) is ReaderControlKind.TRIAL


def test_owned_read_action_is_owned() -> None:
    assert classify_reader_control(
        {"text": "読む", "action": "reading", "href": ""}
    ) is ReaderControlKind.OWNED


def test_purchased_read_action_is_owned() -> None:
    assert classify_reader_control(
        {
            "text": "隱ｭ繧",
            "action": "read_purchased",
            "href": "https://member.bookwalker.jp/app/03/webstore/cooperation",
        }
    ) is ReaderControlKind.OWNED


def test_viewer_href_is_generic_reader_not_owned() -> None:
    metadata = {
        "text": "",
        "action": None,
        "href": "https://viewer.bookwalker.jp/03/30/viewer.html",
    }
    assert classify_reader_control(metadata) is ReaderControlKind.GENERIC_READER
    assert is_reader_control_candidate(metadata)


@pytest.mark.parametrize("action", ["cover", "check", "more_read", "author"])
def test_excluded_control_is_unknown_and_not_a_candidate(action: str) -> None:
    metadata = {"text": "読む", "action": action, "href": "?sample=1"}
    assert classify_reader_control(metadata) is ReaderControlKind.UNKNOWN
    assert not is_reader_control_candidate(metadata)


def test_unknown_control_is_not_a_candidate() -> None:
    assert classify_reader_control({"text": "詳細", "action": None, "href": ""}) is (
        ReaderControlKind.UNKNOWN
    )
    assert not is_reader_control_candidate({"text": "詳細", "action": None, "href": ""})
