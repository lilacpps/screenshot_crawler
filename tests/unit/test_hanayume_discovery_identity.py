import json

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from screenshot_crawler.discovery.models import (
    DiscoveredItem,
    DiscoveredRecord,
    DiscoveredSource,
)
from screenshot_crawler.site_adapters.hanayume.discovery import (
    HanayumeDiscoveryAdapter,
    parse_hanayume_episode_api_identity,
)
from screenshot_crawler.watchlist.models import WatchlistTarget


def _payload(*, episode_id: str = "5fa301a1e55e3", index_id: int = 609597) -> dict:
    return {
        "episode": {
            "id": episode_id,
            "indexId": index_id,
            "series": {"id": "ca6472995ecea"},
            "access": {"episodeId": episode_id},
            "summary": {"id": episode_id, "indexId": index_id},
        },
    }


def test_native_identity_requires_all_consistent_fields() -> None:
    assert parse_hanayume_episode_api_identity(
        _payload(), expected_work_id="ca6472995ecea"
    ) == ("5fa301a1e55e3", 609597)


def test_http_200_negative_payload_is_rejected() -> None:
    assert parse_hanayume_episode_api_identity(
        {"episode": {},}, expected_work_id="ca6472995ecea"
    ) is None


def test_wrong_work_or_disagreeing_summary_is_rejected() -> None:
    payload = _payload()
    payload["episode"]["series"]["id"] = "0000000000001"
    assert parse_hanayume_episode_api_identity(
        payload, expected_work_id="ca6472995ecea"
    ) is None


def _record(
    external_id: str, *, title: str = "scene", position: int = 1
) -> DiscoveredRecord:
    return DiscoveredRecord(
        item=DiscoveredItem(canonical_title=title),
        source=DiscoveredSource(
            external_id=external_id,
            url=f"https://hanayume.com/episodes/{external_id.rsplit(':', 1)[1]}",
            global_display_position=position,
        ),
    )


class _IdentityPage:
    url = "https://hanayume.com/series/ca6472995ecea"

    async def evaluate(self, _script, argument):
        new_id = "5fa301a1e55e3"
        payload = {
            "episode": {
                "id": new_id,
                "indexId": 609597,
                "series": {"id": "ca6472995ecea"},
                "access": {"episodeId": new_id},
                "summary": {"id": new_id, "indexId": 609597},
            }
        }
        if isinstance(argument, list):
            return [{
                "id": argument[0],
                "url": f"https://hanayume.com/api/episodes/{argument[0]}",
                "status": 200,
                "responseUrl": f"https://hanayume.com/api/episodes/{argument[0]}",
                "redirected": False,
                "payload": payload,
            }]
        return {
            "url": f"https://hanayume.com/api/episodes/{argument}",
            "status": 200,
            "responseUrl": f"https://hanayume.com/api/episodes/{argument}",
            "redirected": False,
            "payload": payload,
        }


class _DuplicateMappingPage(_IdentityPage):
    async def evaluate(self, script, argument):
        result = await super().evaluate(script, argument)
        if isinstance(argument, list):
            rows = []
            for old_id in argument:
                row = dict(result[0])
                row["id"] = old_id
                row["url"] = f"https://hanayume.com/api/episodes/{old_id}"
                row["responseUrl"] = row["url"]
                rows.append(row)
            return rows
        return result


class _MismatchedNewResponsePage(_IdentityPage):
    async def evaluate(self, script, argument):
        result = await super().evaluate(script, argument)
        if not isinstance(argument, list):
            result["responseUrl"] = "https://hanayume.com/api/episodes/other"
        return result


class _MixedMappingPage(_IdentityPage):
    async def evaluate(self, script, argument):
        if isinstance(argument, list):
            rows = []
            for old_id in argument:
                episode_id = (
                    "5fa301a1e55e3"
                    if old_id != "3333333333333"
                    else "1111111111111"
                )
                index_id = 609597 if old_id != "3333333333333" else 1
                url = f"https://hanayume.com/api/episodes/{old_id}"
                rows.append({
                    "id": old_id,
                    "url": url,
                    "status": 200,
                    "responseUrl": url,
                    "redirected": False,
                    "payload": _payload(episode_id=episode_id, index_id=index_id),
                })
            return rows
        result = await super().evaluate(script, argument)

        def remap(row, episode_id: str, index_id: int) -> dict:
            row = dict(row)
            row["payload"] = _payload(episode_id=episode_id, index_id=index_id)
            return row

        if argument == "1111111111111":
            return remap(result, "1111111111111", 1)
        return result


class _UnprovenPage(_IdentityPage):
    async def evaluate(self, script, argument):
        result = await super().evaluate(script, argument)

        def remap(row):
            row = dict(row)
            row["payload"] = _payload(episode_id="1111111111111", index_id=1)
            return row

        if isinstance(argument, list):
            return [remap(row) for row in result]
        return remap(result)


@pytest.mark.asyncio
async def test_full_identity_probe_requires_complete_inventory_and_proves_mapping() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    new_external_id = "ca6472995ecea:5fa301a1e55e3"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[new_external_id],
        selected_external_ids={new_external_id}, positions=[1],
    )
    result = await adapter.resolve_identity_changes(
        _IdentityPage(), target,
        ("ca6472995ecea:90fac353b1178",),
        (_record(new_external_id),),
    )
    assert len(result.changes) == 1
    assert result.changes[0].old_external_id == "ca6472995ecea:90fac353b1178"
    assert result.changes[0].new_external_id == new_external_id


@pytest.mark.asyncio
async def test_identity_probe_rejects_unproven_large_missing_set() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=["ca6472995ecea:5fa301a1e55e3"],
        selected_external_ids={"ca6472995ecea:5fa301a1e55e3"}, positions=[1],
    )
    result = await adapter.resolve_identity_changes(
        _IdentityPage(), target,
        tuple(f"ca6472995ecea:{index:013x}" for index in range(17)), (),
    )
    assert result.changes == ()
    assert "bounded limit" in result.diagnostics[0]


@pytest.mark.asyncio
async def test_identity_probe_rejects_foreign_missing_identity() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=["ca6472995ecea:5fa301a1e55e3"],
        selected_external_ids={"ca6472995ecea:5fa301a1e55e3"}, positions=[1],
    )
    result = await adapter.resolve_identity_changes(
        _IdentityPage(), target, ("0000000000001:90fac353b1178",),
        (_record("ca6472995ecea:5fa301a1e55e3"),),
    )
    assert result.changes == ()
    assert "foreign or malformed" in result.diagnostics[0]


@pytest.mark.asyncio
async def test_duplicate_old_ids_to_one_new_id_are_all_rejected() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    new_external_id = "ca6472995ecea:5fa301a1e55e3"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[new_external_id],
        selected_external_ids={new_external_id}, positions=[1],
    )
    result = await adapter.resolve_identity_changes(
        _DuplicateMappingPage(), target,
        ("ca6472995ecea:90fac353b1178", "ca6472995ecea:262ef38505185"),
        (_record(new_external_id),),
    )
    assert result.changes == ()
    assert "one-to-one" in result.diagnostics[0]


@pytest.mark.asyncio
async def test_any_duplicate_mapping_rejects_other_unique_mappings() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    x = "ca6472995ecea:5fa301a1e55e3"
    y = "ca6472995ecea:1111111111111"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[x, y], selected_external_ids={x, y}, positions=[1, 2],
    )
    result = await adapter.resolve_identity_changes(
        _MixedMappingPage(), target,
        (
            "ca6472995ecea:90fac353b1178",
            "ca6472995ecea:262ef38505185",
            "ca6472995ecea:3333333333333",
        ),
        (_record(x), _record(y, position=2)),
    )
    assert result.changes == ()
    assert any("one-to-one" in diagnostic for diagnostic in result.diagnostics)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("title", "position"),
    [("scene", 1), ("番外編", 1), ("前編", 1), ("後編", 1)],
)
async def test_title_and_position_alone_never_merge(
    title: str, position: int
) -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    new_external_id = "ca6472995ecea:5fa301a1e55e3"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[new_external_id],
        selected_external_ids={new_external_id}, positions=[position],
    )
    result = await adapter.resolve_identity_changes(
        _UnprovenPage(), target,
        ("ca6472995ecea:90fac353b1178",),
        (_record(new_external_id, title=title, position=position),),
    )
    assert result.changes == ()
    assert "absent from Full listing" in result.diagnostics[0]


@pytest.mark.asyncio
async def test_new_endpoint_redirect_or_url_mismatch_is_rejected() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    new_external_id = "ca6472995ecea:5fa301a1e55e3"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[new_external_id],
        selected_external_ids={new_external_id}, positions=[1],
    )
    result = await adapter.resolve_identity_changes(
        _MismatchedNewResponsePage(), target,
        ("ca6472995ecea:90fac353b1178",),
        (_record(new_external_id),),
    )
    assert result.changes == ()
    assert "independent new-episode proof failed" in result.diagnostics[0]


@pytest.mark.asyncio
async def test_identity_probe_executes_production_reducer_against_route_fixture() -> None:
    adapter = object.__new__(HanayumeDiscoveryAdapter)
    target = WatchlistTarget(
        key="ng-life", work_key="ng-life", site="hanayume",
        url="https://hanayume.com/series/ca6472995ecea", label="NG LIFE",
    )
    new_external_id = "ca6472995ecea:5fa301a1e55e3"
    adapter.capture_listing_identity_inventory(
        target=target, external_ids=[new_external_id],
        selected_external_ids={new_external_id}, positions=[1],
    )
    episode = {
        "episode": {
            "id": "5fa301a1e55e3", "indexId": 609597,
            "series": {"id": "ca6472995ecea"},
            "access": {"episodeId": "5fa301a1e55e3"},
            "summary": {"id": "5fa301a1e55e3", "indexId": 609597},
        }
    }
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except PlaywrightError as exc:
            pytest.skip(f"Chromium unavailable for route fixture: {exc}")
        context = await browser.new_context()

        async def route(request_route):
            url = request_route.request.url
            if "/api/episodes/" in url:
                await request_route.fulfill(
                    status=200,
                    headers={"content-type": "application/json"},
                    body=json.dumps(episode),
                )
            else:
                await request_route.fulfill(status=200, body="<html></html>")

        await context.route("**/*", route)
        page = await context.new_page()
        await page.goto(target.url)
        result = await adapter.resolve_identity_changes(
            page, target,
            ("ca6472995ecea:90fac353b1178",),
            (_record(new_external_id),),
        )
        await browser.close()
    assert len(result.changes) == 1
    assert result.changes[0].new_external_id == new_external_id
    payload = _payload()
    payload["episode"]["summary"]["id"] = "262ef38505185"
    assert parse_hanayume_episode_api_identity(
        payload, expected_work_id="ca6472995ecea"
    ) is None
