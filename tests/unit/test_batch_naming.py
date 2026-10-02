import pytest

from screenshot_crawler.batch.naming import archive_order_component


@pytest.mark.parametrize(
    ("order_label", "display_position", "expected"),
    [
        ("第一話", 1, "001-第一話"),
        ("番外編", 3, "003-番外編"),
        ("特別編", 1000, "1000-特別編"),
        (None, 3, "003"),
        ("第80話", None, "第80話"),
        (None, None, None),
    ],
)
def test_archive_order_component_uses_position_without_inference(
    order_label: str | None,
    display_position: int | None,
    expected: str | None,
) -> None:
    assert archive_order_component(
        order_label=order_label,
        display_position=display_position,
    ) == expected


def test_archive_order_component_does_not_sanitize_labels() -> None:
    assert archive_order_component(
        order_label="番外/編",
        display_position=3,
    ) == "003-番外/編"
