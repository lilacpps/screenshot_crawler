import json
from types import SimpleNamespace

import pytest

from screenshot_crawler.discovery.service import DiscoveryIncompleteError
from screenshot_crawler.site_adapters.hanayume.discovery import _listing_seed_identity

OLD, NATIVE, WORK = '1111111111111', '2222222222222', '3333333333333'


def payload(identity=NATIVE, index=42, work=WORK):
    return {'episode': {'id': identity, 'indexId': index, 'summary': {'id': identity, 'indexId': index},
        'series': {'id': work}, 'access': {'episodeId': identity}}}


@pytest.mark.parametrize('fault', [None, 'status', 'redirect', 'url', 'type', 'length', 'body',
    'malformed', 'foreign_work', 'old_unchanged', 'new_index', 'new_identity', 'missing_native'])
async def test_alias_requires_both_fixed_endpoints_and_native_listing_membership(fault):
    calls, disposed = [], []

    class Response:
        def __init__(self, url):
            self.url = url + '?unproved=1' if fault == 'url' else url
            self.status = 429 if fault == 'status' else 302 if fault == 'redirect' else 200
            self.headers = {'content-type': 'text/html' if fault == 'type' else 'application/json; charset=utf-8'}
            if fault == 'length':
                self.headers['content-length'] = '2000001'
            data = payload()
            if fault == 'foreign_work':
                data = payload(work='4444444444444')
            if fault == 'old_unchanged':
                data = payload(identity=OLD)
            if url.endswith(NATIVE):
                data = payload(index=43) if fault == 'new_index' else payload(identity=OLD) if fault == 'new_identity' else data
            self.data = json.dumps(data).encode()

        async def body(self):
            return b' ' * 2_000_001 if fault == 'body' else b'{' if fault == 'malformed' else self.data

        async def dispose(self):
            disposed.append(self.url)

    async def get(url, **kwargs):
        assert kwargs == {'max_redirects': 0, 'timeout': 10_000}
        calls.append(url)
        return Response(url)

    page = SimpleNamespace(request=SimpleNamespace(get=get))
    rows = [SimpleNamespace(identity=SimpleNamespace(episode_id='5555555555555' if fault == 'missing_native' else NATIVE))]
    if fault is None:
        assert await _listing_seed_identity(page, seed_id=OLD, work_id=WORK, rows=rows) == NATIVE
    else:
        with pytest.raises(DiscoveryIncompleteError):
            await _listing_seed_identity(page, seed_id=OLD, work_id=WORK, rows=rows)
    assert calls[0] == f'https://hanayume.com/api/episodes/{OLD}'
    assert len(calls) == (2 if fault in {None, 'new_index', 'new_identity'} else 1)
    assert disposed == calls or fault == 'url' and len(disposed) == 1


async def test_present_seed_does_not_fetch_and_duplicate_or_unsafe_ids_do_not_fetch():
    async def forbidden(*args, **kwargs):
        raise AssertionError('Native identity request was not needed')
    page = SimpleNamespace(request=SimpleNamespace(get=forbidden))
    row = SimpleNamespace(identity=SimpleNamespace(episode_id=OLD))
    assert await _listing_seed_identity(page, seed_id=OLD, work_id=WORK, rows=[row]) == OLD
    for seed, rows in ((OLD, [row, row]), ('../consume?x', [row])):
        with pytest.raises(DiscoveryIncompleteError):
            await _listing_seed_identity(page, seed_id=seed, work_id=WORK, rows=rows)
