"""Qt-free, no-write registration drafts. Grouping is an explicit human choice."""

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from screenshot_crawler.registration.models import UrlResolution
from screenshot_crawler.registration.naming import available_name, slug, suggest_name, valid_slug
from screenshot_crawler.registration.resolver import UrlResolver
from screenshot_crawler.watchlist.models import WatchlistTarget

PREVIEW_SITES = frozenset({"magapoke", "jumpplus", "zeblack", "comicdays", "piccoma"})


@dataclass(frozen=True)
class RegistrationCandidate:
    id: str
    origins: tuple[tuple[int, str], ...]
    resolution: UrlResolution
    group_id: str
    label: str = ""
    reading: str = ""
    key: str = ""
    key_manual: bool = False
    confirmed: bool = False
    additional: bool = False
    existing_keys: tuple[str, ...] = ()


@dataclass
class RegistrationWork:
    id: str
    work_key: str
    existing: bool = False
    selected: bool = True
    version: int = 0
    detail: object | None = None


@dataclass(frozen=True)
class WorkReadiness:
    status: str
    reasons: tuple[str, ...] = ()


@dataclass
class BatchRegistrationDraft:
    base: tuple[WatchlistTarget, ...]
    revision: str
    resolver: UrlResolver
    # Catalog-only Works are selectable, but never inferred to own a new URL.
    catalog_works: tuple[tuple[str, str], ...] = ()
    catalog_snapshot: object | None = None
    candidates: dict[str, RegistrationCandidate] = field(default_factory=dict)
    works: dict[str, RegistrationWork] = field(default_factory=dict)
    generation: int = 0
    raw_input: str = ""
    _serial: int = 0
    _owner_data: object | None = field(default=None, init=False, repr=False)
    _owner_basis: tuple = field(default=(), init=False, repr=False)
    _owner_infos: tuple = field(default=(), init=False, repr=False)
    _owner_results: dict = field(default_factory=dict, init=False, repr=False)

    def members(self, group_id: str) -> tuple[RegistrationCandidate, ...]:
        return tuple(row for row in self.candidates.values() if row.group_id == group_id)

    @property
    def existing_works(self) -> dict[str, str]:
        return {**dict(self.catalog_works), **{target.work_key: target.label for target in self.base}}

    def _touch(self, group_id: str) -> None:
        group = self.works[group_id]
        group.version += 1
        group.detail = None
        self.generation += 1

    def _matches(self, result: UrlResolution) -> tuple[str, ...]:
        if result.status == "blocked":
            return ()
        matches = []
        for target in self.base:
            old = self.resolver.resolve(target.url)
            if old.site != result.site or old.status == "blocked":
                continue
            if old.discovery_url == result.discovery_url or (result.site_work_identity
                    and old.site_work_identity == result.site_work_identity):
                matches.append(target.key)
        return tuple(matches)

    def add_resolution(self, line: int, raw: str, result: UrlResolution) -> str:
        for candidate in self.candidates.values():
            old = candidate.resolution
            if result.status != "blocked" and old.status != "blocked" and old.site == result.site and (
                    old.discovery_url == result.discovery_url or (result.site_work_identity
                        and old.site_work_identity == result.site_work_identity)):
                self.candidates[candidate.id] = replace(candidate, origins=(*candidate.origins, (line, raw)))
                return candidate.id
        self._serial += 1
        row_id = str(self._serial)
        suggestion = suggest_name(result.title or "")
        reserved = set(self.existing_works) | {work.work_key for work in self.works.values()}
        work_key = available_name(suggestion.work_key, reserved)
        matches = self._matches(result)
        self.works[row_id] = RegistrationWork(row_id, work_key, selected=not bool(matches))
        self.candidates[row_id] = RegistrationCandidate(row_id, ((line, raw),), result, row_id,
            label=result.title or "", reading=suggestion.reading,
            key=self._key_suggestion(work_key, result.site or "", exclude=row_id), existing_keys=matches)
        self.generation += 1
        return row_id

    def retry(self, candidate_id: str, result: UrlResolution) -> None:
        """Keep every manual field and group; invalidate only this Work's proof."""
        old = self.candidates[candidate_id]
        work = self.works[old.group_id]
        self.candidates[candidate_id] = replace(old, resolution=result, confirmed=False, additional=False,
            key=old.key if old.key_manual else self._key_suggestion(work.work_key,
                result.site or "", exclude=old.id), existing_keys=self._matches(result))
        self._touch(old.group_id)

    def _key_suggestion(self, work_key: str, site: str, *, exclude: str = "") -> str:
        used = {target.key for target in self.base} | {
            row.key for row in self.candidates.values() if row.id != exclude}
        if self.catalog_snapshot is not None:
            used.update(source.discovery_key for source in self.catalog_snapshot.sources if source.discovery_key)
        return available_name(f"{slug(work_key)}_{site}" if slug(work_key) and site else "", used)

    def edit_candidate(self, candidate_id: str, *, label=None, reading=None, key=None) -> None:
        old = self.candidates[candidate_id]
        new = replace(old, label=old.label if label is None else label,
            reading=old.reading if reading is None else reading,
            key=old.key if key is None else key, key_manual=old.key_manual or key is not None,
            confirmed=False, additional=False)
        self.candidates[candidate_id] = new
        self._touch(old.group_id)

    def name_work(self, group_id: str, value: str) -> None:
        group = self.works[group_id]
        if group.existing and value != group.work_key:
            raise ValueError("既存work_keyは変更できません")
        group.work_key = value
        for row in self.members(group_id):
            self.candidates[row.id] = replace(row, confirmed=False, additional=False, key=row.key if row.key_manual
                else self._key_suggestion(value, row.resolution.site or "", exclude=row.id))
        self._touch(group_id)

    def suggest(self, candidate_id: str) -> None:
        row = self.candidates[candidate_id]
        suggestion = suggest_name(row.label, row.reading)
        self.edit_candidate(row.id, reading=suggestion.reading)
        group = self.works[row.group_id]
        if not group.existing:
            reserved = set(self.existing_works) | {w.work_key for w in self.works.values() if w.id != group.id}
            self.name_work(group.id, available_name(suggestion.work_key, reserved))

    def assign(self, candidate_id: str, *, group_id: str | None = None,
               existing_work: str | None = None) -> None:
        row = self.candidates[candidate_id]
        old_group = row.group_id
        if existing_work is not None:
            if existing_work not in self.existing_works:
                raise ValueError("存在しない既存Workです")
            group_id = "existing:" + existing_work
            self.works.setdefault(group_id, RegistrationWork(group_id, existing_work, existing=True))
        elif group_id is None:
            group_id = "new:" + candidate_id
            self.works.setdefault(group_id, RegistrationWork(group_id, ""))
        if group_id not in self.works:
            raise ValueError("所属先Workがありません")
        group = self.works[group_id]
        self.candidates[candidate_id] = replace(row, group_id=group_id, confirmed=False, additional=False,
            key=row.key if row.key_manual else self._key_suggestion(group.work_key,
                row.resolution.site or "", exclude=row.id))
        self._touch(group_id)
        if old_group != group_id:
            if self.members(old_group):
                self._touch(old_group)
            else:
                del self.works[old_group]

    def select(self, group_id: str, selected: bool) -> None:
        self.works[group_id].selected = selected
        self.generation += 1

    def confirm(self, candidate_id: str, *, additional: bool = False) -> None:
        row = self.candidates[candidate_id]
        if row.resolution.status == "blocked":
            raise ValueError("不正・未対応URLは手動確認で登録できません")
        if row.existing_keys and not additional:
            raise ValueError("登録済み候補です。既存key一覧を確認し、追加keyか明示選択してください")
        self.candidates[candidate_id] = replace(row, confirmed=True, additional=additional)
        self._touch(row.group_id)

    def targets_for(self, group_id: str) -> tuple[WatchlistTarget, ...]:
        group = self.works[group_id]
        existing = tuple(target for target in self.base if target.work_key == group.work_key) if group.existing else ()
        return existing + tuple(WatchlistTarget(row.key, group.work_key, row.resolution.site or "",
            row.resolution.discovery_url or "", row.label) for row in self.members(group_id))

    def readiness(self, group_id: str) -> WorkReadiness:
        group = self.works[group_id]
        rows = self.members(group_id)
        blocked, manual = [], []
        for row in rows:
            if row.resolution.status == "blocked":
                blocked.extend(row.resolution.blockers or ("URL blocked",))
            if row.resolution.conversion_proof:
                error = self.resolver.resolution_error(row.resolution)
                if error:
                    blocked.append(error)
            if not row.label.strip() or not valid_slug(row.key) or not row.confirmed:
                manual.append("作品名・Work所属・keyを明示確認してください")
            if row.existing_keys and not row.additional:
                manual.append("登録済み: " + ", ".join(row.existing_keys))
            if row.key and (row.key in {target.key for target in self.base} or any(
                    other.id != row.id and other.key == row.key for other in self.candidates.values())):
                blocked.append("keyが重複しています")
            for other in self.candidates.values():
                result, old = row.resolution, other.resolution
                if (other.group_id != group_id and result.status != "blocked" and old.status != "blocked"
                        and old.site == result.site and (old.discovery_url == result.discovery_url
                            or (result.site_work_identity and old.site_work_identity == result.site_work_identity))):
                    blocked.append("同一URL/作品の候補が別Workにあります。所属を確認してください")
        if group.work_key and not group.existing and (group.work_key in self.existing_works or any(
                other.id != group_id and other.work_key == group.work_key for other in self.works.values())):
            blocked.append("work_keyが別Workと衝突しています。所属を明示指定してください")
        if not group.work_key or (not group.existing and not valid_slug(group.work_key)):
            manual.append("ローマ字work_keyを確定してください")
        members = self.targets_for(group_id)
        if self.catalog_snapshot is not None:
            blocked.extend(self.ownership_blockers(group_id, self.catalog_snapshot))
        needs_detail = group.existing or len(members) > 1
        unsupported = {target.site for target in members} - PREVIEW_SITES
        if needs_detail and unsupported:
            blocked.append("完全一覧preview未対応: " + ", ".join(sorted(unsupported)))
        if blocked:
            return WorkReadiness("blocked", tuple(dict.fromkeys(blocked + manual)))
        if manual:
            return WorkReadiness("needs_manual_confirmation", tuple(dict.fromkeys(manual)))
        if needs_detail and group.detail is None:
            return WorkReadiness("needs_scope", ("全keyの範囲・担当・完成順を詳細編集で確認してください",))
        if group.detail is not None and any(not 0 <= (datetime.now(UTC) - listing.observed_at).total_seconds() <= 300
                for listing in group.detail.listings):
            return WorkReadiness("needs_scope", ("完全一覧が古いため、このWorkを再取得・再確認してください",))
        return WorkReadiness("ready")

    def prepare_ownership(self, data) -> None:
        """Parse immutable Catalog ownership once, in the context-loading worker.

        The cache is object/saved-identity bound, never a substitute for the
        fresh Catalog read performed under the final save lock.
        """
        basis = tuple((row.key, row.work_key, row.site, row.url) for row in self.base)
        if self._owner_data is data and self._owner_basis == basis:
            return
        items = {item.id: item for item in data.items}
        works = {work.id: work.work_key for work in data.works}
        base_by_key = {target.key: target for target in self.base}
        source_urls = {}
        for target in data.targets:
            if target.backend == "web":
                source_urls.setdefault(target.source_id, []).append(target.locator)
        infos = []
        # Repeated web locators or bound keys need no repeated site parsing.
        resolutions_by_url = {}
        def resolve(url):
            if url not in resolutions_by_url:
                resolutions_by_url[url] = self.resolver.resolve(url)
            return resolutions_by_url[url]
        for source in data.sources:
            owner_work = works[items[source.item_id].work_id]
            urls = tuple(source_urls.get(source.id, ()))
            resolutions = tuple(resolve(url) for url in urls)
            error = None
            if any(result.status != "blocked" and result.site != source.site for result in resolutions):
                error = "既存Sourceのweb取得元とサイトが一致しません"
            elif not resolutions or any(old.status == "blocked" for old in resolutions):
                # Only an already bound, consistent native Work identity can
                # disambiguate a viewer-shaped Source; never rewrite its URL.
                bound = base_by_key.get(source.discovery_key)
                known = resolve(bound.url) if bound else None
                if (bound is not None and bound.site == source.site and bound.work_key == owner_work
                        and known.status != "blocked" and known.site_work_identity):
                    if any(old.site_work_identity and old.site_work_identity != known.site_work_identity
                           for old in resolutions if old.status != "blocked"):
                        error = "既存Sourceと所有keyの作品identityが矛盾しています"
                    else:
                        resolutions = (known,)
                else:
                    error = "同一サイトの既存Source URL/所有の照合が未確定です"
            infos.append((source, owner_work, urls, resolutions, error))
        self._owner_data, self._owner_basis, self._owner_infos = data, basis, tuple(infos)
        self._owner_results.clear()

    def ownership_blockers(self, group_id: str, data) -> tuple[str, ...]:
        self.prepare_ownership(data)
        group, members = self.works[group_id], self.members(group_id)
        member_targets = self.targets_for(group_id)
        signature = (group.work_key, member_targets, tuple((row.key, row.resolution, row.existing_keys)
            for row in members))
        previous = self._owner_results.get(group_id)
        if previous is not None and previous[0] == signature:
            return previous[1]
        targets = {target.key: target for target in member_targets}
        new_keys, sites = {row.key for row in members}, {row.resolution.site for row in members}
        errors = []
        for row in members:
            matches = [target for target in self.base if target.key in row.existing_keys]
            if any(target.work_key != group.work_key for target in matches):
                errors.append("同一URL/作品の既存keyが別Workに所属しています")
        for source, owner_work, urls, resolutions, error in self._owner_infos:
            if source.discovery_key in new_keys:
                errors.append("Catalogに既存の所有keyがあります。新規keyで横取り・再所属できません")
            if owner_work == group.work_key and source.acquisition_enabled:
                owner = targets.get(source.discovery_key)
                if owner is None or owner.site != source.site:
                    errors.append("既存Sourceの所有key/サイトが不明です")
            if source.site not in sites:
                continue
            if error:
                errors.append(error)
                continue
            for row in members:
                result = row.resolution
                same = result.discovery_url in urls or any(old.status != "blocked"
                    and old.site == result.site and (old.discovery_url == result.discovery_url
                        or (result.site_work_identity and old.site_work_identity == result.site_work_identity))
                    for old in resolutions)
                if same and owner_work != group.work_key:
                    errors.append("既存Sourceは別Workに所属しています。自動移動できません")
                if same and source.discovery_key is None:
                    errors.append("既存Sourceの所有keyが不明です")
        result = tuple(dict.fromkeys(errors))
        self._owner_results[group_id] = signature, result
        return result

    def title_hints(self, candidate_id: str) -> tuple[tuple[str, str], ...]:
        """Display hints only; calling this never changes membership."""
        label = self.candidates[candidate_id].label.strip().casefold()
        return tuple((key, title) for key, title in self.existing_works.items()
                     if label and title.strip().casefold() == label)
