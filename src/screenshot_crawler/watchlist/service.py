"""Load and update the deliberately small ``watchlist.yaml`` format."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from screenshot_crawler.catalog.job_lock import CatalogJobLock
from screenshot_crawler.watchlist.models import ArchiveSegment, DiscoveryScope, WatchlistTarget


class WatchlistError(ValueError):
    """Base error for invalid or unmodifiable watchlists."""


class InvalidWatchlistError(WatchlistError):
    """Raised when the YAML does not match the watchlist schema."""


class DuplicateWatchlistKeyError(WatchlistError):
    """Raised when a watchlist contains or adds a duplicate key."""


class WatchlistTargetNotFoundError(WatchlistError):
    """Raised when an operation refers to an unknown target."""


@dataclass(frozen=True, slots=True)
class WatchlistEditPreview:
    """Read-only result for a proposed Watchlist edit."""

    current_revision: str
    targets: tuple[WatchlistTarget, ...]
    changed_keys: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.blockers


_UNSET = object()


class WatchlistService:
    """Repository for a human-editable YAML watchlist.

    A missing file and a genuinely empty file represent an empty watchlist.
    Any non-empty YAML document must explicitly contain a list-valued
    ``targets`` field.
    """

    def __init__(self, path: str | Path = "watchlist.yaml") -> None:
        self.path = Path(path)
        self._cached_document: tuple[str, tuple[WatchlistTarget, ...]] | None = None

    def list_targets(self) -> list[WatchlistTarget]:
        """Return targets in file order."""

        return self._load()

    list = list_targets

    def get(self, key: str) -> WatchlistTarget:
        """Return a target by its stable key."""

        for target in self._load():
            if target.key == key:
                return target
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def revision(self) -> str:
        """Return the SHA-256 revision of the current file contents."""

        return self._content_digest(self._read_content())

    content_digest = revision

    def edit_lock(self) -> CatalogJobLock:
        """Return the per-Watchlist CAS/replace lock.

        The shared lock primitive is path-keyed and works across processes on
        Windows and POSIX.  It is used only for Watchlist file edits; no
        Catalog data is touched.
        """

        return CatalogJobLock(self.path)

    def preview_edit(
        self,
        targets: Iterable[WatchlistTarget],
        *,
        expected_revision: str | None = None,
    ) -> WatchlistEditPreview:
        """Validate a proposed target set without writing or touching Catalog."""

        current_content = self._read_content()
        current_revision = self._content_digest(current_content)
        blockers: list[str] = []
        if expected_revision is not None and expected_revision != current_revision:
            blockers.append("Watchlist changed since the edit was started; reload and retry")
        proposed = list(targets)
        try:
            proposed = self._validate_targets(proposed)
        except WatchlistError as exc:
            blockers.append(str(exc))
        current = self._load()
        changed = tuple(
            target.key
            for target in proposed
            if next((row for row in current if row.key == target.key), None) != target
        )
        changed += tuple(row.key for row in current if row.key not in {t.key for t in proposed})
        changed += tuple(row.key for row in proposed if row.key not in {t.key for t in current})
        return WatchlistEditPreview(
            current_revision=current_revision,
            targets=tuple(proposed),
            changed_keys=tuple(dict.fromkeys(changed)),
            blockers=tuple(dict.fromkeys(blockers)),
        )

    def apply_edit(
        self,
        targets: Iterable[WatchlistTarget],
        *,
        expected_revision: str | None = None,
    ) -> tuple[WatchlistTarget, ...]:
        """Atomically save a complete editor proposal under one Watchlist CAS."""

        with self.edit_lock():
            expected_content = self._content_for_revision(expected_revision)
            current = self._load_content(expected_content)
            proposed = self._validate_targets(list(targets))
            if proposed == current:
                return tuple(current)
            self._write(proposed, previous=current, expected_content=expected_content)
            return tuple(proposed)

    update_targets = apply_edit

    def add(
        self,
        *,
        key: str,
        work_key: str,
        site: str,
        url: str,
        label: str,
        enabled: bool = True,
        discovery_scope: DiscoveryScope | None = None,
        archive_order: int | None = None,
        archive_segments: Iterable[ArchiveSegment] | None = None,
        expected_revision: str | None = None,
    ) -> WatchlistTarget:
        """Add a target, rejecting an already-used stable key."""

        target = self._validate_target(
            WatchlistTarget(
                key=key, work_key=work_key, site=site, url=url, label=label,
                enabled=enabled, discovery_scope=discovery_scope,
                archive_order=archive_order,
                archive_segments=None if archive_segments is None else tuple(archive_segments),
            ),
            source="new target",
        )
        with self.edit_lock():
            expected_content = self._content_for_revision(expected_revision)
            targets = self._load_content(expected_content)
            if any(existing.key == target.key for existing in targets):
                raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
            targets.append(target)
            self._write(targets, previous=targets[:-1], expected_content=expected_content)
        return target

    def update_target(
        self,
        key: str,
        *,
        label: str | object = _UNSET,
        url: str | object = _UNSET,
        enabled: bool | object = _UNSET,
        discovery_scope: DiscoveryScope | None | object = _UNSET,
        archive_segments: Iterable[ArchiveSegment] | None | object = _UNSET,
        expected_revision: str | None = None,
    ) -> WatchlistTarget:
        """Update editable fields of one key using an optimistic revision check."""

        with self.edit_lock():
            expected_content = self._content_for_revision(expected_revision)
            targets = self._load_content(expected_content)
            for index, current in enumerate(targets):
                if current.key != key:
                    continue
                updated = WatchlistTarget(
                    key=current.key,
                    work_key=current.work_key,
                    site=current.site,
                    url=current.url if url is _UNSET else url,  # type: ignore[arg-type]
                    label=current.label if label is _UNSET else label,  # type: ignore[arg-type]
                    enabled=current.enabled if enabled is _UNSET else enabled,  # type: ignore[arg-type]
                    discovery_scope=(
                        current.discovery_scope
                        if discovery_scope is _UNSET
                        else discovery_scope  # type: ignore[arg-type]
                    ),
                    archive_order=current.archive_order,
                    archive_segments=(
                        current.archive_segments
                        if archive_segments is _UNSET
                        else None if archive_segments is None else tuple(archive_segments)  # type: ignore[arg-type]
                    ),
                )
                updated = self._validate_target(updated, source=f"target {key!r}")
                if updated == current:
                    return current
                targets[index] = updated
                self._write(
                    targets,
                    previous=[*targets[:index], current, *targets[index + 1:]],
                    expected_content=expected_content,
                )
                return updated
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def update_work_archive_order(
        self,
        work_key: str,
        orders: Mapping[str, int | None] | Sequence[str],
        *,
        expected_revision: str | None = None,
    ) -> tuple[WatchlistTarget, ...]:
        """Atomically update every key's archive order within one Work."""

        with self.edit_lock():
            expected_content = self._content_for_revision(expected_revision)
            targets = self._load_content(expected_content)
            members = [target for target in targets if target.work_key == work_key]
            if not members:
                raise WatchlistTargetNotFoundError(f"Watchlist work not found: {work_key}")
            if isinstance(orders, Mapping):
                if set(orders) != {target.key for target in members}:
                    raise InvalidWatchlistError(
                        f"archive_order update must cover every key in work_key {work_key!r}"
                    )
                values = dict(orders)
            else:
                order_keys = list(orders)
                if set(order_keys) != {target.key for target in members} or len(order_keys) != len(members):
                    raise InvalidWatchlistError(
                        f"archive_order update must cover every key in work_key {work_key!r}"
                    )
                values = {key: index for index, key in enumerate(order_keys, start=1)}
            updated = [
                WatchlistTarget(
                    key=target.key,
                    work_key=target.work_key,
                    site=target.site,
                    url=target.url,
                    label=target.label,
                    enabled=target.enabled,
                    discovery_scope=target.discovery_scope,
                    archive_order=values[target.key],
                    archive_segments=target.archive_segments,
                )
                if target.work_key == work_key else target
                for target in targets
            ]
            updated = self._validate_targets(updated)
            if updated == targets:
                return tuple(members)
            self._write(updated, previous=targets, expected_content=expected_content)
            return tuple(target for target in updated if target.work_key == work_key)

    def remove(self, key: str) -> WatchlistTarget:
        """Remove a target without touching any Catalog data."""

        with self.edit_lock():
            expected_content = self._content_for_revision(None)
            targets = self._load_content(expected_content)
            for index, target in enumerate(targets):
                if target.key == key:
                    removed = targets.pop(index)
                    previous = [*targets[:index], removed, *targets[index:]]
                    self._write(targets, previous=previous, expected_content=expected_content)
                    return removed
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def set_enabled(self, key: str, enabled: bool) -> WatchlistTarget:
        """Enable or disable a target without touching any Catalog data."""

        with self.edit_lock():
            expected_content = self._content_for_revision(None)
            targets = self._load_content(expected_content)
            for index, target in enumerate(targets):
                if target.key == key:
                    updated = WatchlistTarget(
                        key=target.key,
                        work_key=target.work_key,
                        site=target.site,
                        url=target.url,
                        label=target.label,
                        enabled=enabled,
                        discovery_scope=target.discovery_scope,
                        archive_order=target.archive_order,
                        archive_segments=target.archive_segments,
                    )
                    updated = self._validate_target(updated, source=f"target {key!r}")
                    targets[index] = updated
                    previous = [*targets[:index], target, *targets[index + 1 :]]
                    self._write(targets, previous=previous, expected_content=expected_content)
                    return updated
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def enable(self, key: str) -> WatchlistTarget:
        return self.set_enabled(key, True)

    def disable(self, key: str) -> WatchlistTarget:
        return self.set_enabled(key, False)

    add_target = add
    remove_target = remove
    enable_target = enable
    disable_target = disable

    def _read_content(self) -> str:
        if not self.path.exists():
            return ""
        try:
            # Preserve CRLF bytes for CAS/revision and lossless YAML patches.
            return self.path.read_bytes().decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise InvalidWatchlistError(f"Cannot read watchlist {self.path}: {exc}") from exc

    @staticmethod
    def _content_digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _content_for_revision(self, expected_revision: str | None) -> str | None:
        content = self._read_content()
        if expected_revision is not None and self._content_digest(content) != expected_revision:
            raise WatchlistError(
                "Watchlist changed since the edit was started; reload and retry"
            )
        return content

    def _validate_targets(self, targets: list[WatchlistTarget]) -> list[WatchlistTarget]:
        keys: set[str] = set()
        normalized: list[WatchlistTarget] = []
        for index, target in enumerate(targets):
            target = self._validate_target(target, source=f"targets[{index}]")
            if target.key in keys:
                raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
            keys.add(target.key)
            normalized.append(target)
        self._validate_archive_orders(normalized)
        return normalized

    def _load(self) -> list[WatchlistTarget]:
        return self._load_content(self._read_content())

    def _load_content(self, content: str) -> list[WatchlistTarget]:
        if not self.path.exists():
            return []
        try:
            # Content comparison also catches same-size edits and atomic replacements.
            cached = self._cached_document
            if cached is not None and content == cached[0]:
                return list(cached[1])
            raw = yaml.safe_load(content)
        except (OSError, UnicodeError) as exc:
            raise InvalidWatchlistError(f"Cannot read watchlist {self.path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise InvalidWatchlistError(f"Malformed YAML in {self.path}: {exc}") from exc

        if raw is None:
            self._cached_document = (content, ())
            return []
        if not isinstance(raw, dict):
            raise InvalidWatchlistError("Watchlist root must be a mapping")
        if "targets" not in raw:
            raise InvalidWatchlistError("Watchlist must contain a 'targets' field")
        raw_targets = raw["targets"]
        if not isinstance(raw_targets, list):
            raise InvalidWatchlistError("Watchlist 'targets' must be a list")

        targets: list[WatchlistTarget] = []
        keys: set[str] = set()
        for index, raw_target in enumerate(raw_targets):
            target = self._parse_target(raw_target, index)
            if target.key in keys:
                raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
            keys.add(target.key)
            targets.append(target)
        self._validate_archive_orders(targets)
        # Read the file on every call; only parsing unchanged content is shared.
        # Rows are immutable and callers receive a fresh list.
        self._cached_document = (content, tuple(targets))
        return targets

    def _parse_target(self, raw_target: Any, index: int) -> WatchlistTarget:
        if not isinstance(raw_target, dict):
            raise InvalidWatchlistError(f"targets[{index}] must be a mapping")
        required = ("key", "work_key", "site", "url", "label")
        missing = [field for field in required if field not in raw_target]
        if missing:
            raise InvalidWatchlistError(
                f"targets[{index}] is missing required field(s): {', '.join(missing)}"
            )
        enabled = raw_target.get("enabled", True)
        label = raw_target.get("label")
        if not isinstance(enabled, bool):
            raise InvalidWatchlistError(f"targets[{index}].enabled must be a boolean")
        if not isinstance(label, str):
            raise InvalidWatchlistError(f"targets[{index}].label must be a string")
        discovery_scope = self._parse_discovery_scope(raw_target, index)
        archive_order = raw_target.get("archive_order")
        if "archive_order" in raw_target and (
            isinstance(archive_order, bool)
            or not isinstance(archive_order, int)
            or archive_order < 1
        ):
            raise InvalidWatchlistError(
                f"targets[{index}].archive_order must be a positive integer"
            )
        archive_segments = self._parse_archive_segments(raw_target, index)
        return self._validate_target(
            WatchlistTarget(
                work_key=raw_target["work_key"],
                key=raw_target["key"],
                site=raw_target["site"],
                url=raw_target["url"],
                label=label,
                enabled=enabled,
                discovery_scope=discovery_scope,
                archive_order=archive_order,
                archive_segments=archive_segments,
            ),
            source=f"targets[{index}]",
        )

    @staticmethod
    def _parse_discovery_scope(raw_target: Mapping[str, Any], index: int) -> DiscoveryScope | None:
        if "discovery_scope" not in raw_target:
            return None
        raw_scope = raw_target["discovery_scope"]
        if not isinstance(raw_scope, Mapping):
            raise InvalidWatchlistError(f"targets[{index}].discovery_scope must be a mapping")

        from_url = WatchlistService._parse_scope_url(raw_scope, "from_url", index)
        through_url = WatchlistService._parse_scope_url(raw_scope, "through_url", index)
        excluded = WatchlistService._parse_excluded_external_ids(raw_scope, index)
        if from_url is None and through_url is None and not excluded:
            if "excluded_external_ids" in raw_scope:
                return None
            raise InvalidWatchlistError(
                f"targets[{index}].discovery_scope must contain from_url, through_url, "
                "or excluded_external_ids"
            )
        return DiscoveryScope(
            from_url=from_url,
            through_url=through_url,
            excluded_external_ids=excluded,
        )

    @staticmethod
    def _parse_archive_segments(
        raw_target: Mapping[str, Any], index: int
    ) -> tuple[ArchiveSegment, ...] | None:
        if "archive_segments" not in raw_target:
            return None
        raw_segments = raw_target["archive_segments"]
        if not isinstance(raw_segments, (list, tuple)):
            raise InvalidWatchlistError(
                f"targets[{index}].archive_segments must be a list"
            )
        result: list[ArchiveSegment] = []
        for segment_index, raw_segment in enumerate(raw_segments):
            source = f"targets[{index}].archive_segments[{segment_index}]"
            if not isinstance(raw_segment, Mapping):
                raise InvalidWatchlistError(f"{source} must be a mapping")
            order = raw_segment.get("order")
            if isinstance(order, bool) or not isinstance(order, int) or order < 1:
                raise InvalidWatchlistError(f"{source}.order must be a positive integer")
            values: dict[str, str | None] = {}
            for field in ("start_external_id", "end_external_id"):
                value = raw_segment.get(field)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise InvalidWatchlistError(f"{source}.{field} must be a non-empty string")
                values[field] = value
            result.append(
                ArchiveSegment(
                    order=order,
                    start_external_id=values["start_external_id"],
                    end_external_id=values["end_external_id"],
                )
            )
        return tuple(result)

    @staticmethod
    def _parse_excluded_external_ids(
        raw_scope: Mapping[str, Any], index: int
    ) -> tuple[str, ...]:
        if "excluded_external_ids" not in raw_scope:
            return ()
        value = raw_scope["excluded_external_ids"]
        if value is None:
            raise InvalidWatchlistError(
                f"targets[{index}].discovery_scope.excluded_external_ids must be a list"
            )
        if not isinstance(value, (list, tuple)):
            raise InvalidWatchlistError(
                f"targets[{index}].discovery_scope.excluded_external_ids must be a list"
            )
        return WatchlistService._normalize_excluded_external_ids(
            value, source=f"targets[{index}].discovery_scope.excluded_external_ids"
        )

    @staticmethod
    def _normalize_excluded_external_ids(
        values: Iterable[object], *, source: str
    ) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise InvalidWatchlistError(f"{source} must contain non-empty strings")
            if value in seen:
                raise InvalidWatchlistError(f"{source} contains duplicate ID {value!r}")
            seen.add(value)
            normalized.append(value)
        return tuple(sorted(normalized))

    @staticmethod
    def _parse_scope_url(
        raw_scope: Mapping[str, Any], field: str, index: int
    ) -> str | None:
        if field not in raw_scope:
            return None
        value = raw_scope[field]
        if not isinstance(value, str) or not value.strip():
            raise InvalidWatchlistError(
                f"targets[{index}].discovery_scope.{field} must be a non-empty string"
            )
        return value

    @staticmethod
    def _validate_target(target: WatchlistTarget, *, source: str) -> WatchlistTarget:
        for name in ("key", "work_key", "site", "url", "label"):
            value = getattr(target, name)
            if not isinstance(value, str) or not value.strip():
                raise InvalidWatchlistError(f"{source}.{name} must be a non-empty string")
        if not isinstance(target.enabled, bool):
            raise InvalidWatchlistError(f"{source}.enabled must be a boolean")
        if target.archive_order is not None and (
            isinstance(target.archive_order, bool)
            or not isinstance(target.archive_order, int)
            or target.archive_order < 1
        ):
            raise InvalidWatchlistError(f"{source}.archive_order must be a positive integer")
        if target.archive_segments is not None:
            if not isinstance(target.archive_segments, (tuple, list)):
                raise InvalidWatchlistError(f"{source}.archive_segments must be a list")
            if target.archive_order is not None:
                raise InvalidWatchlistError(
                    f"{source} cannot specify both archive_order and archive_segments"
                )
            normalized_segments: list[ArchiveSegment] = []
            for segment_index, segment in enumerate(target.archive_segments):
                if not isinstance(segment, ArchiveSegment):
                    raise InvalidWatchlistError(
                        f"{source}.archive_segments[{segment_index}] must be an ArchiveSegment"
                    )
                if (
                    isinstance(segment.order, bool)
                    or not isinstance(segment.order, int)
                    or segment.order < 1
                ):
                    raise InvalidWatchlistError(
                        f"{source}.archive_segments[{segment_index}].order must be a positive integer"
                    )
                for field in ("start_external_id", "end_external_id"):
                    value = getattr(segment, field)
                    if value is not None and (not isinstance(value, str) or not value.strip()):
                        raise InvalidWatchlistError(
                            f"{source}.archive_segments[{segment_index}].{field} must be a non-empty string"
                        )
                normalized_segments.append(
                    ArchiveSegment(
                        order=segment.order,
                        start_external_id=segment.start_external_id,
                        end_external_id=segment.end_external_id,
                    )
                )
            target = replace(target, archive_segments=tuple(normalized_segments))
        if target.discovery_scope is not None:
            if not isinstance(target.discovery_scope, DiscoveryScope):
                raise InvalidWatchlistError(f"{source}.discovery_scope must be a DiscoveryScope")
            for field in ("from_url", "through_url"):
                value = getattr(target.discovery_scope, field)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise InvalidWatchlistError(
                        f"{source}.discovery_scope.{field} must be a non-empty string"
                    )
            normalized = WatchlistService._normalize_excluded_external_ids(
                target.discovery_scope.excluded_external_ids,
                source=f"{source}.discovery_scope.excluded_external_ids",
            )
            if (
                target.discovery_scope.from_url is None
                and target.discovery_scope.through_url is None
                and not normalized
            ):
                return replace(target, discovery_scope=None)
            target = replace(
                target,
                discovery_scope=DiscoveryScope(
                    from_url=target.discovery_scope.from_url,
                    through_url=target.discovery_scope.through_url,
                    excluded_external_ids=normalized,
                ),
            )
        return target

    @staticmethod
    def _validate_archive_orders(targets: list[WatchlistTarget]) -> None:
        by_work: dict[str, list[WatchlistTarget]] = {}
        for target in targets:
            by_work.setdefault(target.work_key, []).append(target)
        for work_key, members in by_work.items():
            segment_members = [member for member in members if member.archive_segments is not None]
            if segment_members:
                if len(segment_members) != len(members):
                    raise InvalidWatchlistError(
                        f"work_key {work_key!r} must specify archive_segments for every key or none"
                    )
                segment_orders = [
                    segment.order
                    for member in members
                    for segment in member.archive_segments or ()
                ]
                if len(segment_orders) != len(set(segment_orders)):
                    raise InvalidWatchlistError(
                        f"work_key {work_key!r} has duplicate archive_segments order values"
                    )
                if any(member.archive_order is not None for member in members):
                    raise InvalidWatchlistError(
                        f"work_key {work_key!r} cannot mix archive_order and archive_segments"
                    )
                continue
            specified = [member.archive_order is not None for member in members]
            if any(specified) and not all(specified):
                raise InvalidWatchlistError(
                    f"work_key {work_key!r} must specify archive_order for every key or none"
                )
            orders = [member.archive_order for member in members if member.archive_order is not None]
            if len(orders) != len(set(orders)):
                raise InvalidWatchlistError(
                    f"work_key {work_key!r} has duplicate archive_order values"
                )

    def _write(
        self,
        targets: list[WatchlistTarget],
        *,
        previous: list[WatchlistTarget] | None = None,
        expected_content: str | None = None,
    ) -> None:
        self._validate_archive_orders(targets)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current_content = self._read_content()
        if expected_content is not None and current_content != expected_content:
            raise WatchlistError(
                "Watchlist changed while saving; reload and retry the edit"
            )
        if self.path.exists() and previous is not None:
            original = current_content
            if self._needs_lossless_patch(original):
                patched = self._patch_existing_yaml(original, previous, targets)
                if patched is None:
                    raise WatchlistError(
                        f"Cannot safely update {self.path} while preserving its comments; "
                        "edit the target mapping directly"
                    )
                self._validate_written_content(patched, targets)
                self._atomic_write(self._preserve_eol(patched, original))
                return
            content = self._preserve_eol(self._serialize_targets(targets), original)
            self._validate_written_content(content, targets)
            self._atomic_write(content)
            return
        content = self._serialize_targets(targets)
        self._validate_written_content(content, targets)
        self._atomic_write(content)

    @staticmethod
    def _contains_comments(content: str) -> bool:
        # A raw '#' may be a real YAML comment, a URL fragment, or part of a
        # multiline quoted scalar. Treat all cases conservatively: scalar-only
        # patches remain safe, while structural rewrites must not risk erasing
        # comment-like or quoted source text.
        return "#" in content

    @classmethod
    def _needs_lossless_patch(cls, content: str) -> bool:
        if cls._contains_comments(content):
            return True
        try:
            raw = yaml.safe_load(content)
        except yaml.YAMLError:
            return True
        if not isinstance(raw, dict):
            return True
        if set(raw) - {"targets"}:
            return True
        targets = raw.get("targets")
        if not isinstance(targets, list):
            return False
        known = {
            "key", "work_key", "site", "url", "enabled", "label",
            "discovery_scope", "archive_order",
            "archive_segments",
        }
        for value in targets:
            if not isinstance(value, dict):
                continue
            if set(value) - known:
                return True
            scope = value.get("discovery_scope")
            if isinstance(scope, dict) and set(scope) - {
                "from_url", "through_url", "excluded_external_ids"
            }:
                return True
            segments = value.get("archive_segments")
            if isinstance(segments, list) and any(
                not isinstance(segment, dict)
                or set(segment) - {"order", "start_external_id", "end_external_id"}
                for segment in segments
            ):
                return True
        return False

    def _serialize_targets(self, targets: list[WatchlistTarget]) -> str:
        serialized_targets: list[dict[str, Any]] = []
        for target in targets:
            serialized_targets.append(self._target_mapping(target))
        payload = {"targets": serialized_targets}
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)

    def _validate_written_content(
        self, content: str, expected: list[WatchlistTarget]
    ) -> None:
        try:
            raw = yaml.safe_load(content)
            if not isinstance(raw, dict) or not isinstance(raw.get("targets"), list):
                raise InvalidWatchlistError("written Watchlist targets are not a list")
            actual = [self._parse_target(target, index) for index, target in enumerate(raw["targets"])]
            keys = [target.key for target in actual]
            if len(keys) != len(set(keys)):
                raise InvalidWatchlistError("written Watchlist has duplicate keys")
            self._validate_archive_orders(actual)
            expected_normalized = self._validate_targets(list(expected))
            if actual != expected_normalized:
                raise InvalidWatchlistError("written Watchlist does not match the requested targets")
        except (yaml.YAMLError, InvalidWatchlistError) as exc:
            raise WatchlistError(
                f"Refusing to write invalid or incomplete Watchlist content: {exc}"
            ) from exc

    @staticmethod
    def _target_mapping(target: WatchlistTarget) -> dict[str, Any]:
        value: dict[str, Any] = {
            "key": target.key,
            "work_key": target.work_key,
            "site": target.site,
            "url": target.url,
            "enabled": target.enabled,
            "label": target.label,
        }
        if target.discovery_scope is not None:
            scope: dict[str, Any] = {}
            if target.discovery_scope.from_url is not None:
                scope["from_url"] = target.discovery_scope.from_url
            if target.discovery_scope.through_url is not None:
                scope["through_url"] = target.discovery_scope.through_url
            if target.discovery_scope.excluded_external_ids:
                scope["excluded_external_ids"] = list(
                    target.discovery_scope.excluded_external_ids
                )
            value["discovery_scope"] = scope
        if target.archive_order is not None:
            value["archive_order"] = target.archive_order
        if target.archive_segments is not None:
            value["archive_segments"] = [
                {
                    "order": segment.order,
                    **({"start_external_id": segment.start_external_id}
                       if segment.start_external_id is not None else {}),
                    **({"end_external_id": segment.end_external_id}
                       if segment.end_external_id is not None else {}),
                }
                for segment in target.archive_segments
            ]
        return value

    def _patch_existing_yaml(
        self,
        original: str,
        previous: list[WatchlistTarget],
        targets: list[WatchlistTarget],
    ) -> str | None:
        """Patch ordinary block YAML while retaining unrelated comments/keys.

        PyYAML is used only for source spans.  We intentionally reject flow
        collections and ambiguous mappings; callers then leave the original
        file untouched instead of silently reserializing it.
        """

        try:
            root = yaml.compose(original)
        except yaml.YAMLError:
            return None
        if not isinstance(root, yaml.MappingNode):
            return None
        sequence = next(
            (
                value
                for key, value in root.value
                if isinstance(key, yaml.ScalarNode) and key.value == "targets"
            ),
            None,
        )
        if not isinstance(sequence, yaml.SequenceNode) or sequence.flow_style:
            return None
        old_by_key = {target.key: target for target in previous}
        new_by_key = {target.key: target for target in targets}
        if len(old_by_key) != len(previous) or len(new_by_key) != len(targets):
            return None

        lines = original.splitlines(keepends=True)
        starts = self._line_starts(lines)
        item_infos: dict[str, tuple[yaml.MappingNode, int, int, int]] = {}
        item_starts: list[int] = []
        for node in sequence.value:
            if not isinstance(node, yaml.MappingNode) or node.flow_style:
                return None
            if any(
                isinstance(value, yaml.ScalarNode)
                and (
                    "\n" in str(value.value)
                    or value.style in {"|", ">"}
                    or "\n" in original[value.start_mark.index : value.end_mark.index]
                )
                for _key, value in node.value
            ):
                return None
            key_node = next(
                (
                    value
                    for key, value in node.value
                    if isinstance(key, yaml.ScalarNode) and key.value == "key"
                ),
                None,
            )
            if not isinstance(key_node, yaml.ScalarNode) or not isinstance(key_node.value, str):
                return None
            key_line = self._line_for_index(starts, key_node.start_mark.index)
            item_line = key_line
            while item_line >= 0 and not re.match(r"^\s*-\s+", lines[item_line]):
                item_line -= 1
            if item_line < 0:
                return None
            item_starts.append(item_line)
            item_infos[key_node.value] = (node, item_line, 0, len(lines))
        item_starts_sorted = sorted(item_starts)
        for key, (node, item_line, _unused, _end) in list(item_infos.items()):
            next_line = next((line for line in item_starts_sorted if line > item_line), len(lines))
            # The last item can be followed by an unrelated root field. PyYAML's
            # collection end includes trailing comments, so trim those separately.
            node_end_line = node.end_mark.line + bool(node.end_mark.column)
            next_line = min(next_line, node_end_line)
            dash_indent = len(lines[item_line]) - len(lines[item_line].lstrip())
            field_indent = dash_indent + 2
            item_infos[key] = (node, item_line, field_indent, next_line)

        edits: list[tuple[int, int, str]] = []
        removed_keys = set(old_by_key) - set(new_by_key)
        added_keys = set(new_by_key) - set(old_by_key)
        for key in removed_keys:
            info = item_infos.get(key)
            if info is None:
                return None
            _node, start_line, _indent, end_line = info
            kept = [
                line
                for line in lines[start_line:end_line]
                if not line.strip() or line.lstrip().startswith("#")
            ]
            edits.append((starts[start_line], starts[end_line] if end_line < len(starts) else len(original), "".join(kept)))

        for key in sorted(added_keys):
            if not item_starts_sorted:
                append_at = sequence.start_mark.index
                indent = 0
            else:
                append_at = sequence.end_mark.index
                indent = len(lines[item_starts_sorted[0]]) - len(lines[item_starts_sorted[0]].lstrip())
            rendered = self._render_target_item(new_by_key[key], indent)
            edits.append((append_at, append_at, rendered))

        for key in sorted(set(old_by_key) & set(new_by_key)):
            old, new = old_by_key[key], new_by_key[key]
            if old == new:
                continue
            if any(getattr(old, field) != getattr(new, field) for field in ("key", "work_key", "site")):
                return None
            info = item_infos.get(key)
            if info is None:
                return None
            node, start_line, field_indent, end_line = info
            direct_nodes = {
                str(field.value): value
                for field, value in node.value
                if isinstance(field, yaml.ScalarNode)
            }
            additions: dict[str, list[str]] = {}
            for field in ("url", "label", "enabled", "archive_order"):
                old_value = getattr(old, field)
                new_value = getattr(new, field)
                if old_value == new_value:
                    continue
                field_span = self._field_span(lines, starts, start_line, end_line, field, field_indent)
                value_node = direct_nodes.get(field)
                if new_value is None:
                    if field_span is None:
                        return None
                    edits.append(field_span)
                elif isinstance(value_node, yaml.ScalarNode) and field_span is not None:
                    edits.append((value_node.start_mark.index, value_node.end_mark.index, self._render_scalar(new_value)))
                else:
                    additions[field] = self._render_field(field, new_value, field_indent)

            if old.discovery_scope != new.discovery_scope:
                scope_span = self._field_span(
                    lines, starts, start_line, end_line, "discovery_scope", field_indent
                )
                if old.discovery_scope is None and new.discovery_scope is not None:
                    additions["discovery_scope"] = self._render_scope(new.discovery_scope, field_indent)
                elif new.discovery_scope is None:
                    if scope_span is None:
                        return None
                    edits.append(scope_span)
                else:
                    if scope_span is None:
                        additions["discovery_scope"] = self._render_scope(new.discovery_scope, field_indent)
                    else:
                        scope_node = direct_nodes.get("discovery_scope")
                        if isinstance(scope_node, yaml.MappingNode) and any(
                            not isinstance(field, yaml.ScalarNode)
                            or str(field.value)
                            not in {"from_url", "through_url", "excluded_external_ids"}
                            for field, _value in scope_node.value
                        ):
                            return None
                        if "#" in original[scope_span[0] : scope_span[1]]:
                            return None
                        edits.append((scope_span[0], scope_span[1], "".join(self._render_scope(new.discovery_scope, field_indent))))
            if old.archive_segments != new.archive_segments:
                segments_span = self._field_span(
                    lines, starts, start_line, end_line, "archive_segments", field_indent
                )
                if old.archive_segments is None and new.archive_segments is not None:
                    additions["archive_segments"] = self._render_archive_segments(new.archive_segments, field_indent)
                elif new.archive_segments is None:
                    if segments_span is None:
                        return None
                    edits.append(segments_span)
                elif segments_span is None:
                    additions["archive_segments"] = self._render_archive_segments(new.archive_segments, field_indent)
                else:
                    if "#" in original[segments_span[0] : segments_span[1]]:
                        return None
                    segments_node = direct_nodes.get("archive_segments")
                    if not isinstance(segments_node, yaml.SequenceNode) or segments_node.flow_style:
                        return None
                    if any(
                        not isinstance(segment_node, yaml.MappingNode)
                        or segment_node.flow_style
                        or any(
                            not isinstance(field, yaml.ScalarNode)
                            or str(field.value)
                            not in {"order", "start_external_id", "end_external_id"}
                            for field, _value in segment_node.value
                        )
                        for segment_node in segments_node.value
                    ):
                        return None
                    edits.append(
                        (
                            segments_span[0],
                            segments_span[1],
                            "".join(self._render_archive_segments(new.archive_segments, field_indent)),
                        )
                    )
            if additions:
                # Leave the original separator and the next Work's heading after
                # the entire target, rather than between its old and new fields.
                insert_line = end_line
                while insert_line > start_line and (
                    not lines[insert_line - 1].strip()
                    or (
                        lines[insert_line - 1].lstrip().startswith("#")
                        and len(lines[insert_line - 1]) - len(lines[insert_line - 1].lstrip()) <= field_indent
                    )
                ):
                    insert_line -= 1
                insert_at = starts[insert_line] if insert_line < len(starts) else len(original)
                rendered = "".join(
                    line for field in self._target_mapping(new)
                    for line in additions.get(field, ())
                )
                if insert_at and original[insert_at - 1] not in "\r\n":
                    rendered = "\n" + rendered
                edits.append((insert_at, insert_at, rendered))

        patched = original
        for start, end, replacement in sorted(edits, key=lambda item: (item[0], item[1]), reverse=True):
            if start > end or start < 0 or end > len(patched):
                return None
            patched = patched[:start] + replacement + patched[end:]
        if not targets:
            patched = re.sub(
                r"(?m)^(?P<indent>\s*)targets:\s*(?P<comment>#.*)?\r?\n",
                lambda match: (
                    f"{match.group('indent')}targets: []"
                    + (f" {match.group('comment')}" if match.group('comment') else "")
                    + "\n"
                ),
                patched,
                count=1,
            )
        return patched

    @staticmethod
    def _line_starts(lines: list[str]) -> list[int]:
        result: list[int] = []
        offset = 0
        for line in lines:
            result.append(offset)
            offset += len(line)
        return result

    @staticmethod
    def _line_for_index(starts: list[int], index: int) -> int:
        for line, start in enumerate(starts):
            if start > index:
                return max(0, line - 1)
        return max(0, len(starts) - 1)

    @classmethod
    def _field_span(
        cls,
        lines: list[str],
        starts: list[int],
        item_start: int,
        item_end: int,
        field: str,
        indent: int,
    ) -> tuple[int, int, str] | None:
        pattern = re.compile(rf"^{' ' * indent}{re.escape(field)}\s*:")
        line = next(
            (index for index in range(item_start, item_end) if pattern.match(lines[index])),
            None,
        )
        if line is None:
            return None
        end = line + 1
        while end < item_end:
            current = lines[end]
            stripped = current.strip()
            if stripped and not stripped.startswith("#"):
                current_indent = len(current) - len(current.lstrip())
                if current_indent <= indent:
                    break
            end += 1
        # Blank separators and peer-level comments belong outside this field.
        # Keep deeper comments inside its span so structural rewrites still
        # reject nested comments rather than silently discarding them.
        while end > line + 1:
            current = lines[end - 1]
            if not current.strip() or (
                current.lstrip().startswith("#")
                and len(current) - len(current.lstrip()) <= indent
            ):
                end -= 1
            else:
                break
        return starts[line], starts[end] if end < len(starts) else sum(len(value) for value in lines), ""

    @staticmethod
    def _render_scalar(value: object) -> str:
        rendered = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True)
        return " ".join(line.strip() for line in rendered.splitlines() if line.strip() != "...")

    @classmethod
    def _render_scope(cls, scope: DiscoveryScope, indent: int) -> list[str]:
        prefix = " " * indent
        nested = " " * (indent + 2)
        lines = [f"{prefix}discovery_scope:\n"]
        if scope.from_url is not None:
            lines.append(f"{nested}from_url: {cls._render_scalar(scope.from_url)}\n")
        if scope.through_url is not None:
            lines.append(f"{nested}through_url: {cls._render_scalar(scope.through_url)}\n")
        if scope.excluded_external_ids:
            lines.append(f"{nested}excluded_external_ids:\n")
            lines.extend(
                f"{' ' * (indent + 4)}- {cls._render_scalar(value)}\n"
                for value in scope.excluded_external_ids
            )
        return lines

    @classmethod
    def _render_archive_segments(
        cls, segments: tuple[ArchiveSegment, ...], indent: int
    ) -> list[str]:
        prefix = " " * indent
        nested = " " * (indent + 2)
        detail = " " * (indent + 4)
        if not segments:
            return [f"{prefix}archive_segments: []\n"]
        lines = [f"{prefix}archive_segments:\n"]
        for segment in segments:
            lines.append(f"{nested}- order: {cls._render_scalar(segment.order)}\n")
            if segment.start_external_id is not None:
                lines.append(
                    f"{detail}start_external_id: {cls._render_scalar(segment.start_external_id)}\n"
                )
            if segment.end_external_id is not None:
                lines.append(
                    f"{detail}end_external_id: {cls._render_scalar(segment.end_external_id)}\n"
                )
        return lines

    @classmethod
    def _render_field(cls, field: str, value: object, indent: int) -> list[str]:
        return [f"{' ' * indent}{field}: {cls._render_scalar(value)}\n"]

    @classmethod
    def _render_target_item(cls, target: WatchlistTarget, indent: int) -> str:
        serialized = yaml.safe_dump(
            {"targets": [cls._target_mapping(target)]},
            allow_unicode=True,
            sort_keys=False,
        )
        body = serialized.split("targets:\n", 1)[1]
        return "".join(" " * indent + line if line.strip() else line for line in body.splitlines(keepends=True))

    def _atomic_write(self, content: str) -> None:
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(content.encode("utf-8"))
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise WatchlistError(f"Cannot write watchlist {self.path}: {exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _preserve_eol(content: str, original: str) -> str:
        """Use the existing file's newline convention for generated text."""

        if "\r\n" in original:
            return content.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
        return content.replace("\r\n", "\n").replace("\r", "\n")
