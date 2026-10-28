"""Catalog-free, identity-based Work editing used by the GUI.

Rows remain site/key specific. A replacement changes selection and sequence,
never the identity or completion state of a Catalog Source.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from screenshot_crawler.discovery.listing import ListingPreview, ListingRow
from screenshot_crawler.watchlist.models import ArchiveSegment, DiscoveryScope, WatchlistTarget
from screenshot_crawler.watchlist.selection import SelectionPlanner


@dataclass(frozen=True)
class DraftBlock:
    key: str
    start_external_id: str | None = None
    end_external_id: str | None = None


def interval_rows(listing: ListingPreview, start: str | None, end: str | None) -> tuple[ListingRow, ...]:
    rows = tuple(sorted(listing.rows, key=lambda row: row.site_position))
    ids = [row.external_id for row in rows]
    if start is not None and start not in ids or end is not None and end not in ids:
        raise ValueError("範囲の境界が完全一覧にありません")
    first = ids.index(start) if start is not None else 0
    last = ids.index(end) if end is not None else len(rows) - 1
    if first > last:
        raise ValueError("開始と終了が逆転しています")
    return rows[first:last + 1]


def selected_rows(target: WatchlistTarget, listing: ListingPreview) -> tuple[ListingRow, ...]:
    scope = target.discovery_scope
    rows = tuple(listing.rows)  # Discovery's canonical newest-first order.
    if scope is None:
        return tuple(reversed(rows))
    urls = [row.url for row in rows]
    if any(url is not None and url not in urls for url in (scope.from_url, scope.through_url)):
        raise ValueError(f"{target.key}: 保存済み範囲の境界が一覧にありません")
    first = urls.index(scope.from_url) if scope.from_url else 0
    last = urls.index(scope.through_url) if scope.through_url else len(rows) - 1
    if first > last:
        raise ValueError(f"{target.key}: 保存済み範囲が逆転しています")
    if not set(scope.excluded_external_ids).issubset({row.external_id for row in rows[first:last + 1]}):
        raise ValueError(f"{target.key}: 除外IDが範囲外です")
    return tuple(row for row in reversed(rows[first:last + 1]) if row.external_id not in scope.excluded_external_ids)


class WorkDraft:
    """One Work's draft; unrelated Watchlist rows remain in ``targets``."""

    def __init__(self, targets: Iterable[WatchlistTarget], work_key: str) -> None:
        self.targets = tuple(targets)
        self.work_key = work_key
        self.listings: dict[str, ListingPreview] = {}
        self.new_keys: set[str] = set()
        self.configured_keys: set[str] = set()

    @property
    def members(self) -> tuple[WatchlistTarget, ...]:
        return tuple(target for target in self.targets if target.work_key == self.work_key)

    def target(self, key: str) -> WatchlistTarget:
        return next(target for target in self.members if target.key == key)

    def update(self, target: WatchlistTarget) -> None:
        self.targets = tuple(target if old.key == target.key else old for old in self.targets)

    def add(self, target: WatchlistTarget) -> None:
        if target.work_key != self.work_key or any(row.key == target.key for row in self.targets):
            raise ValueError("work_keyが異なるか、keyが重複しています")
        if any(member.archive_order is not None for member in self.members):
            target = replace(target, archive_order=max(member.archive_order or 0 for member in self.members) + 1)
        self.targets += (target,)
        self.new_keys.add(target.key)

    def set_listing(self, listing: ListingPreview) -> None:
        target = self.target(listing.target_key)
        if (listing.site, listing.target_url) != (target.site, target.url):
            raise ValueError("一覧のsite/key/URLが下書きと一致しません")
        errors: list[str] = []
        SelectionPlanner._validate_listing(listing, errors)
        if not listing.rows:
            errors.append("完全一覧が空です")
        if errors:
            raise ValueError(" / ".join(errors))
        self.listings[target.key] = listing

    def blocks(self) -> list[DraftBlock]:
        if any(target.archive_segments is not None for target in self.members):
            result = [DraftBlock(target.key, segment.start_external_id, segment.end_external_id)
                    for _order, target, segment in sorted(
                        (segment.order, target, segment)
                        for target in self.members for segment in target.archive_segments or ())]
            result.extend(DraftBlock(target.key) for target in self.members if target.archive_segments is None)
            return result
        result = []
        members = sorted(enumerate(self.members), key=lambda pair: (pair[1].archive_order or 10**9, pair[0]))
        for _index, target in members:
            listing = self.listings[target.key]
            selected = {row.external_id for row in selected_rows(target, listing)}
            rows = tuple(reversed(listing.rows))
            runs: list[list[ListingRow]] = []
            for index, row in enumerate(rows):
                if row.external_id in selected:
                    if not runs or (index and rows[index - 1].external_id not in selected):
                        runs.append([])
                    runs[-1].append(row)
            for run in runs:
                scope = target.discovery_scope
                result.append(DraftBlock(target.key,
                    None if run[0] == rows[0] and (scope is None or scope.through_url is None) else run[0].external_id,
                    None if run[-1] == rows[-1] and (scope is None or scope.from_url is None) else run[-1].external_id))
        return result

    def rows_for_block(self, block: DraftBlock) -> tuple[ListingRow, ...]:
        return interval_rows(self.listings[block.key], block.start_external_id, block.end_external_id)

    def set_range(self, key: str, start: str | None, end: str | None) -> None:
        listing = self.listings[key]
        rows = interval_rows(listing, start, end)
        if not rows:
            raise ValueError("担当範囲が空です")
        if any(target.archive_segments is not None for target in self.members):
            blocks = self.blocks()
            own = [index for index, block in enumerate(blocks) if block.key == key]
            if len(own) > 1:
                raise ValueError("複数区間のkeyです。完成順で区間を選んで範囲を編集してください")
            index = own[0] if own else len(blocks)
            blocks = [block for block in blocks if block.key != key]
            blocks.insert(index, DraftBlock(key, start, end))
            self.apply_blocks(blocks)
        else:
            self.update(replace(self.target(key), discovery_scope=self._scope(key, {row.external_id for row in rows}, start is None, end is None)))
        self.configured_keys.add(key)

    def _scope(self, key: str, selected: set[str], open_oldest: bool, open_latest: bool) -> DiscoveryScope | None:
        rows = tuple(reversed(self.listings[key].rows))
        if not selected:
            return DiscoveryScope(rows[-1].url, rows[0].url, tuple(sorted(row.external_id for row in rows)))
        indices = [index for index, row in enumerate(rows) if row.external_id in selected]
        first, last = min(indices), max(indices)
        holes = tuple(sorted(row.external_id for row in rows[first:last + 1] if row.external_id not in selected))
        scope = DiscoveryScope(None if open_latest else rows[last].url,
                               None if open_oldest else rows[first].url, holes)
        return None if scope.from_url is None and scope.through_url is None and not holes else scope

    def apply_blocks(self, blocks: Iterable[DraftBlock]) -> None:
        blocks = tuple(blocks)
        segments: dict[str, list[ArchiveSegment]] = {target.key: [] for target in self.members}
        selected: dict[str, set[str]] = {key: set() for key in segments}
        opened: dict[str, list[bool]] = {key: [False, False] for key in segments}
        for index, block in enumerate(blocks, 1):
            if block.key not in segments:
                raise ValueError("区間が別作品のkeyを参照しています")
            rows = self.rows_for_block(block)
            ids = {row.external_id for row in rows}
            if not ids or ids & selected[block.key]:
                raise ValueError("完成順に空区間または重複した話があります")
            selected[block.key].update(ids)
            opened[block.key][0] |= block.start_external_id is None
            opened[block.key][1] |= block.end_external_id is None
            segments[block.key].append(ArchiveSegment(index, block.start_external_id, block.end_external_id))
        updated = {target.key: replace(target, archive_order=None,
            archive_segments=tuple(segments[target.key]),
            discovery_scope=self._scope(target.key, selected[target.key], *opened[target.key]))
            for target in self.members}
        self.targets = tuple(updated.get(target.key, target) for target in self.targets)

    @staticmethod
    def _slice(block: DraftBlock, rows: tuple[ListingRow, ...], first: int, last: int) -> DraftBlock:
        return DraftBlock(block.key,
            block.start_external_id if first == 0 else rows[first].external_id,
            block.end_external_id if last == len(rows) - 1 else rows[last].external_id)

    def replace_range(self, source_key: str, first: str, last: str,
                      destination_key: str, start: str, end: str) -> tuple[int, int]:
        if source_key == destination_key:
            raise ValueError("置換元と置換先は別keyを選択してください")
        source_ids = {row.external_id for row in interval_rows(self.listings[source_key], first, last)}
        destination_rows = interval_rows(self.listings[destination_key], start, end)
        destination_ids = {row.external_id for row in destination_rows}
        found = False
        result: list[DraftBlock] = []
        for block in self.blocks():
            rows = self.rows_for_block(block)
            ids = [row.external_id for row in rows]
            if block.key == source_key and source_ids.issubset(ids):
                a, b = ids.index(first), ids.index(last)
                if a:
                    result.append(self._slice(block, rows, 0, a - 1))
                result.append(DraftBlock(destination_key, start, end))
                if b + 1 < len(rows):
                    result.append(self._slice(block, rows, b + 1, len(rows) - 1))
                found = True
            elif block.key == destination_key:
                if destination_key in self.new_keys and destination_key not in self.configured_keys:
                    continue  # The new key's default all-episodes selection is not a request.
                keep = [index for index, external_id in enumerate(ids) if external_id not in destination_ids]
                while keep:
                    a = b = keep.pop(0)
                    while keep and keep[0] == b + 1:
                        b = keep.pop(0)
                    result.append(self._slice(block, rows, a, b))
            else:
                result.append(block)
        if not found:
            raise ValueError("置換元は完成順の1つの区間内から連続して選択してください")
        self.apply_blocks(result)
        self.configured_keys.add(destination_key)
        return len(source_ids), len(destination_ids)

    def validate(self, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        for target in self.members:
            listing = self.listings.get(target.key)
            if listing is None:
                raise ValueError(f"{target.key}: 完全一覧を取得してください")
            self.set_listing(listing)
            age = (now - listing.observed_at).total_seconds()
            if not 0 <= age <= 300:
                raise ValueError(f"{target.key}: 完全一覧が古いため再取得してください")
        assigned: dict[str, set[str]] = {target.key: set() for target in self.members}
        for block in self.blocks():
            ids = {row.external_id for row in self.rows_for_block(block)}
            if ids & assigned[block.key]:
                raise ValueError("完成順の話が重複しています")
            assigned[block.key].update(ids)
        for target in self.members:
            if assigned[target.key] != {row.external_id for row in selected_rows(target, self.listings[target.key])}:
                raise ValueError(f"{target.key}: 担当範囲と完成順が一致しません")


def full_changed_keys(before: Iterable[WatchlistTarget], after: Iterable[WatchlistTarget]) -> frozenset[str]:
    old = {target.key: target for target in before}
    result: set[str] = set()
    order_works: set[str] = set()
    after = tuple(after)
    for target in after:
        previous = old.get(target.key)
        if previous is None or previous.url != target.url or previous.discovery_scope != target.discovery_scope:
            result.add(target.key)
        if previous is not None and (previous.archive_order, previous.archive_segments) != (target.archive_order, target.archive_segments):
            order_works.add(target.work_key)
    result.update(target.key for target in after if target.work_key in order_works)
    return frozenset(result)
