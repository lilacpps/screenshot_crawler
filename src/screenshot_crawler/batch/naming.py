"""Shared Catalog-to-archive naming primitives for Batch and later tooling."""

from __future__ import annotations


def archive_order_component(
    *,
    order_label: str | None,
    display_position: int | None,
) -> str | None:
    """Return the desired archive order component.

    A known display position is the ordering authority and is rendered with a
    minimum width of three digits.  The label is deliberately left otherwise
    untouched; Windows filename sanitization remains the responsibility of
    :func:`screenshot_crawler.core.packaging.safe_component`.
    """

    if display_position is not None:
        prefix = f"{display_position:03d}"
        if order_label is not None and order_label.strip():
            return f"{prefix}-{order_label}"
        return prefix
    if order_label is not None and order_label.strip():
        return order_label
    return None
