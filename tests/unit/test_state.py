from screenshot_crawler.core.state import PageState


def test_page_state_values_are_stable() -> None:
    assert PageState.CONTENT.value == "content"
    assert PageState.UNKNOWN.value == "unknown"
