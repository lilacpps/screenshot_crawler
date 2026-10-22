"""Load and update the deliberately small ``watchlist.yaml`` format."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from screenshot_crawler.watchlist.models import DiscoveryScope, WatchlistTarget


class WatchlistError(ValueError):
    """Base error for invalid or unmodifiable watchlists."""


class InvalidWatchlistError(WatchlistError):
    """Raised when the YAML does not match the watchlist schema."""


class DuplicateWatchlistKeyError(WatchlistError):
    """Raised when a watchlist contains or adds a duplicate key."""


class WatchlistTargetNotFoundError(WatchlistError):
    """Raised when an operation refers to an unknown target."""


class WatchlistService:
    """Repository for a human-editable YAML watchlist.

    A missing file and a genuinely empty file represent an empty watchlist.
    Any non-empty YAML document must explicitly contain a list-valued
    ``targets`` field.
    """

    def __init__(self, path: str | Path = "watchlist.yaml") -> None:
        self.path = Path(path)

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

    def add(
        self,
        *,
        key: str,
        work_key: str,
        site: str,
        url: str,
        label: str,
        enabled: bool = True,
        archive_order: int | None = None,
    ) -> WatchlistTarget:
        """Add a target, rejecting an already-used stable key."""

        target = self._validate_target(
            WatchlistTarget(
                key=key, work_key=work_key, site=site, url=url, label=label,
                enabled=enabled, archive_order=archive_order,
            ),
            source="new target",
        )
        targets = self._load()
        if any(existing.key == target.key for existing in targets):
            raise DuplicateWatchlistKeyError(f"Duplicate watchlist key: {target.key}")
        targets.append(target)
        self._write(targets, previous=targets[:-1])
        return target

    def remove(self, key: str) -> WatchlistTarget:
        """Remove a target without touching any Catalog data."""

        targets = self._load()
        for index, target in enumerate(targets):
            if target.key == key:
                removed = targets.pop(index)
                previous = [*targets[:index], removed, *targets[index:]]
                self._write(targets, previous=previous)
                return removed
        raise WatchlistTargetNotFoundError(f"Watchlist target not found: {key}")

    def set_enabled(self, key: str, enabled: bool) -> WatchlistTarget:
        """Enable or disable a target without touching any Catalog data."""

        targets = self._load()
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
                )
                targets[index] = updated
                previous = [*targets[:index], target, *targets[index + 1 :]]
                self._write(targets, previous=previous)
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

    def _load(self) -> list[WatchlistTarget]:
        if not self.path.exists():
            return []
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise InvalidWatchlistError(f"Cannot read watchlist {self.path}: {exc}") from exc
        except yaml.YAMLError as exc:
            raise InvalidWatchlistError(f"Malformed YAML in {self.path}: {exc}") from exc

        if raw is None:
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
        if from_url is None and through_url is None:
            raise InvalidWatchlistError(
                f"targets[{index}].discovery_scope must contain from_url or through_url"
            )
        return DiscoveryScope(from_url=from_url, through_url=through_url)

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
        if target.discovery_scope is not None:
            if not isinstance(target.discovery_scope, DiscoveryScope):
                raise InvalidWatchlistError(f"{source}.discovery_scope must be a DiscoveryScope")
            if target.discovery_scope.from_url is None and target.discovery_scope.through_url is None:
                raise InvalidWatchlistError(
                    f"{source}.discovery_scope must contain from_url or through_url"
                )
            for field in ("from_url", "through_url"):
                value = getattr(target.discovery_scope, field)
                if value is not None and (not isinstance(value, str) or not value.strip()):
                    raise InvalidWatchlistError(
                        f"{source}.discovery_scope.{field} must be a non-empty string"
                    )
        return target

    @staticmethod
    def _validate_archive_orders(targets: list[WatchlistTarget]) -> None:
        by_work: dict[str, list[WatchlistTarget]] = {}
        for target in targets:
            by_work.setdefault(target.work_key, []).append(target)
        for work_key, members in by_work.items():
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
    ) -> None:
        self._validate_archive_orders(targets)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and previous is not None:
            original = self.path.read_text(encoding="utf-8")
            if self._contains_comments(original):
                patched = self._patch_existing_yaml(original, previous, targets)
                if patched is None:
                    raise WatchlistError(
                        f"Cannot safely update {self.path} while preserving its comments; "
                        "edit the target mapping directly"
                    )
                self._validate_written_content(patched, targets)
                self._atomic_write(patched)
                return
            content = self._serialize_targets(targets)
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
            if actual != expected:
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
            scope: dict[str, str] = {}
            if target.discovery_scope.from_url is not None:
                scope["from_url"] = target.discovery_scope.from_url
            if target.discovery_scope.through_url is not None:
                scope["through_url"] = target.discovery_scope.through_url
            value["discovery_scope"] = scope
        if target.archive_order is not None:
            value["archive_order"] = target.archive_order
        return value

    def _patch_existing_yaml(
        self,
        original: str,
        previous: list[WatchlistTarget],
        targets: list[WatchlistTarget],
    ) -> str | None:
        """Patch only changed target spans so comments and formatting survive."""

        try:
            root = yaml.compose(original)
        except yaml.YAMLError:
            return None
        if not isinstance(root, yaml.MappingNode):
            return None
        sequence = next(
            (value for key, value in root.value if isinstance(key, yaml.ScalarNode) and key.value == "targets"),
            None,
        )
        if not isinstance(sequence, yaml.SequenceNode):
            return None
        if sequence.flow_style:
            return None
        old_by_key = {target.key: target for target in previous}
        new_by_key = {target.key: target for target in targets}
        removed = set(old_by_key) - set(new_by_key)
        added = set(new_by_key) - set(old_by_key)
        if removed or added:
            return None
        edits: list[tuple[int, int, str]] = []
        node_by_key: dict[str, yaml.MappingNode] = {}
        for node in sequence.value:
            if not isinstance(node, yaml.MappingNode):
                return None
            key_node = next(
                (value for key, value in node.value if isinstance(key, yaml.ScalarNode) and key.value == "key"),
                None,
            )
            if not isinstance(key_node, yaml.ScalarNode):
                return None
            node_by_key[key_node.value] = node

        changed_fields = {"enabled"}
        for key in set(old_by_key) & set(new_by_key):
            old, new = old_by_key[key], new_by_key[key]
            if old == new:
                continue
            if old.archive_order != new.archive_order:
                return None
            if any(
                getattr(old, field) != getattr(new, field)
                for field in ("key", "work_key", "site", "url", "label", "discovery_scope")
            ):
                return None
            node = node_by_key.get(key)
            if node is None:
                return None
            for field in changed_fields:
                old_value = getattr(old, field)
                new_value = getattr(new, field)
                if old_value == new_value:
                    continue
                pair = next(
                    ((k, v) for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == field),
                    None,
                )
                if pair is None:
                    return None
                value_node = pair[1]
                if not isinstance(value_node, yaml.ScalarNode):
                    return None
                rendered = "true" if new_value is True else "false" if new_value is False else str(new_value)
                edits.append((value_node.start_mark.index, value_node.end_mark.index, rendered))

        patched = original
        for start, end, replacement in sorted(edits, reverse=True):
            patched = patched[:start] + replacement + patched[end:]
        return patched

    def _atomic_write(self, content: str) -> None:
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = temporary.name
                temporary.write(content)
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
