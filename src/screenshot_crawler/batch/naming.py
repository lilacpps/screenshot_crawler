"""Shared Catalog-to-archive naming primitives for Batch and maintenance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from screenshot_crawler.catalog.models import Item, Source, Work
from screenshot_crawler.core.packaging import archive_stem


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


def archive_metadata_for_catalog(work: Work, item: Item, source: Source) -> dict[str, str]:
    """Build the packaging metadata used by both Batch and archive renumbering."""

    order = archive_order_component(
        order_label=item.order_label,
        display_position=source.display_position,
    )
    metadata: dict[str, str] = {}
    for field_name, value in (
        ("title", work.title),
        ("author", work.author),
        ("order", order),
        ("genre", work.genre),
    ):
        if value is not None and value.strip():
            metadata[field_name] = value
    return metadata


def catalog_archive_stem(
    work: Work,
    item: Item,
    source: Source,
    *,
    artifact_disambiguator: str | None = None,
) -> str:
    """Return the exact P3 archive stem for a Catalog Work/Item/Source."""

    stem, *_ = archive_stem(
        archive_metadata_for_catalog(work, item, source),
        artifact_disambiguator=artifact_disambiguator,
    )
    return stem


def collision_source_ids(
    works: Iterable[Work],
    items: Iterable[Item],
    sources: Iterable[Source],
) -> set[int]:
    """Return sources in P3 same-site Work/stem collision groups.

    The caller supplies one site-scoped snapshot.  All item statuses participate,
    and multiple Sources for one Item do not create a collision by themselves.
    """

    works_by_id = {work.id: work for work in works}
    items_by_id = {item.id: item for item in items}
    groups: dict[tuple[int, str], list[tuple[int, int]]] = defaultdict(list)
    for source in sources:
        item = items_by_id.get(source.item_id)
        work = works_by_id.get(item.work_id) if item is not None else None
        if item is None or work is None:
            continue
        base_stem = catalog_archive_stem(work, item, source)
        groups[(work.id, base_stem)].append((item.id, source.id))

    result: set[int] = set()
    for entries in groups.values():
        if len({item_id for item_id, _ in entries}) >= 2:
            result.update(source_id for _, source_id in entries)
    return result
