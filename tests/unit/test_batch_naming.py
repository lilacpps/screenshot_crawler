import pytest

from screenshot_crawler.batch.naming import archive_position_prefix


@pytest.mark.parametrize(
    ("display_position", "expected"),
    [(1, "001"), (3, "003"), (999, "999"), (1000, "1000"), (None, None)],
)
def test_archive_position_prefix_does_not_infer_from_missing_position(
    display_position: int | None,
    expected: str | None,
) -> None:
    assert archive_position_prefix(display_position) == expected
