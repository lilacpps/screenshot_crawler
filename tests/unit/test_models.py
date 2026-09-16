from screenshot_crawler.core.models import ContentContext, ContentIdentity


def test_content_identity_is_value_comparable() -> None:
    assert ContentIdentity(page_number=1, source_id="a") == ContentIdentity(
        page_number=1,
        source_id="a",
    )


def test_content_context_is_value_comparable() -> None:
    assert ContentContext(episode_id="42") == ContentContext(episode_id="42")
