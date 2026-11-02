"""Fixed readonly metadata API, exercised with an isolated local HTTP upstream."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest
from playwright.async_api import APIRequestContext, Error

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.resolver import UrlResolver
from screenshot_crawler.site_adapters.zeblack.discovery_protobuf import MAX_PROTOBUF_BODY_BYTES

pytestmark = pytest.mark.asyncio(loop_scope="module")
URL = 'https://zebrack-comic.shueisha.co.jp/title/00123'
API = 'https://api2.zebrack-comic.com/api/browser/title_detail?os=browser&title_id=00123&tab=detail'


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result) + bytes([value])


def field(number, value):
    return (varint(number << 3) + varint(value) if isinstance(value, int)
            else varint((number << 3) | 2) + varint(len(value)) + value)


def payload(mode):
    identity = field(1, 999 if mode == 'wrong_id' else 123)
    name = field(2, b'\xff' if mode == 'invalid_utf8' else b'' if mode == 'empty_title' else '人工作品２！'.encode())
    detail = (b'' if mode == 'missing_id' else identity * (2 if mode == 'duplicate_id' else 1))
    detail += b'' if mode == 'missing_name' else name * (2 if mode == 'duplicate_name' else 1)
    data = field(21, detail) * (2 if mode == 'duplicate_root' else 1)
    if mode == 'api_error':
        data += field(1000, b'error')
    if mode == 'malformed':
        data = b'\xff'
    if mode == 'oversize':
        data = b'\x00' * (MAX_PROTOBUF_BODY_BYTES + 1)
    return data


@pytest.mark.parametrize('mode', [
    'ok', 'wrong_id', 'missing_id', 'missing_name', 'empty_title', 'invalid_utf8',
    'duplicate_id', 'duplicate_name', 'duplicate_root', 'api_error', 'malformed',
    'oversize', 'declared_oversize', 'bad_length', 'wrong_type', 'redirect', 'http_error',
    'unexpected_url', 'transport',
])
async def test_fixed_metadata_get_and_native_binding(browser_page, monkeypatch, mode):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302 if mode == 'redirect' else 503 if mode == 'http_error' else 200)
            self.send_header('Content-Type', 'text/html' if mode == 'wrong_type' else 'application/protobuf')
            if mode == 'redirect':
                self.send_header('Location', 'https://foreign.invalid/')
            self.end_headers()
            self.wfile.write(payload(mode))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    calls, disposed, get = [], [], APIRequestContext.get

    class Response:
        def __init__(self, response):
            self.response = response
            self.url = API + '&extra=1' if mode == 'unexpected_url' else API
            self.status = response.status
            self.headers = response.headers
            if mode in {'declared_oversize', 'bad_length'}:
                self.headers['content-length'] = str(MAX_PROTOBUF_BODY_BYTES + 1) if mode == 'declared_oversize' else 'invalid'

        async def body(self):
            return await self.response.body()

        async def dispose(self):
            disposed.append(True)
            await self.response.dispose()

    async def upstream(context, url, **kwargs):
        calls.append((url, kwargs))
        if mode == 'transport':
            raise Error('synthetic transport error')
        response = await get(context, f'http://127.0.0.1:{server.server_port}/', **kwargs)
        return Response(response)

    monkeypatch.setattr(APIRequestContext, 'get', upstream)
    resolver = UrlResolver(_discovery_registry())
    initial = resolver.resolve(URL)
    try:
        result = await resolver.observe(browser_page, initial)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert calls == [(API, {'max_redirects': 0, 'timeout': 20_000})]
    assert disposed == ([] if mode == 'transport' else [True])
    assert browser_page.url == 'about:blank'  # Neither shell nor viewer initialized.
    assert result.discovery_url == initial.discovery_url
    assert result.site_work_identity == initial.site_work_identity
    if mode == 'ok':
        assert result.title == '人工作品２！' and result.status == 'converted'
        assert resolver.resolution_error(result) is None
    elif mode in {'wrong_id', 'duplicate_id', 'duplicate_name', 'duplicate_root', 'redirect', 'unexpected_url'}:
        assert result.status == 'blocked' and result.title is None
    else:
        assert result.status == 'converted' and result.title is None and result.warnings
