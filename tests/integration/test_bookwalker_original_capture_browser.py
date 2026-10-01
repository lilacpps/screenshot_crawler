from __future__ import annotations

import base64

import pytest
from playwright.async_api import Page

from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _SELECTED_COMPLETED_MAPPINGS_SCRIPT,
    BookWalkerAdapter,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    image_signature,
    imagebitmap_signature,
)
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    analyze_purchased_mapping,
)

pytestmark = pytest.mark.asyncio(loop_scope="module")


class _PreparePage:
    def __init__(self) -> None:
        self.listener_count = 0
        self.route_count = 0
        self.init_scripts: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    def on(self, _event: str, _handler: object) -> None:
        self.listener_count += 1

    async def route(self, _pattern: str, _handler: object) -> None:
        self.route_count += 1


async def test_native_capture_mode_init_script_controls_trace(
    browser_page: Page,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = BookWalkerAdapter()
    prepared = _PreparePage()
    await adapter.prepare_page(prepared)  # type: ignore[arg-type]
    assert len(prepared.init_scripts) == 1
    mode_script = prepared.init_scripts[0]

    async def evaluate_scripts(url: str, scripts: tuple[str, ...]) -> dict[str, object]:
        browser = browser_page.context.browser
        assert browser is not None
        context = await browser.new_context()
        page = await context.new_page()

        async def fulfill(route: object) -> None:
            await route.fulfill(status=200, body="<html></html>")  # type: ignore[attr-defined]

        await page.route(f"{url}**", fulfill)  # type: ignore[arg-type]
        try:
            for script in scripts:
                await page.add_init_script(script)
            await page.goto(url)
            return await page.evaluate(
                "() => ({ mode: window.__bookwalkerCaptureMode, "
                "enabled: window.__bookwalkerNativeCaptureEnabled, "
                "installed: window.__bookwalkerDrawTraceInstalled })"
            )
        finally:
            await page.close()
            await context.close()

    draw_script = adapter_module._DRAW_TRACE_SCRIPT
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/order-a",
        ("window.__bookwalkerCaptureMode = 'native';", draw_script),
    ) == {"mode": "native", "enabled": True, "installed": True}
    assert await evaluate_scripts(
        "https://viewer.bookwalker.jp/production",
        (mode_script,),
    ) == {"mode": "native", "enabled": True, "installed": True}

    monkeypatch.setenv("BOOKWALKER_CAPTURE_MODE", "canvas")
    canvas_adapter = BookWalkerAdapter()
    canvas_prepared = _PreparePage()
    await canvas_adapter.prepare_page(canvas_prepared)  # type: ignore[arg-type]
    assert len(canvas_prepared.init_scripts) == 1
    assert await evaluate_scripts(
        "https://trial.bookwalker.jp/production",
        (canvas_prepared.init_scripts[0],),
    ) == {"mode": "canvas", "enabled": False, "installed": True}


async def test_html_canvas_snapshot_is_pixel_stable_until_materialize(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")

    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 2;
          source.height = 2;
          document.body.appendChild(source);
          const sourceContext = source.getContext('2d');
          sourceContext.fillStyle = 'black';
          sourceContext.fillRect(0, 0, 2, 2);

          const renderer = document.createElement('canvas');
          renderer.width = 1200;
          renderer.height = 600;
          document.body.appendChild(renderer);
          const rendererContext = renderer.getContext('2d');
          const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
          let toDataURLCalls = 0;
          HTMLCanvasElement.prototype.toDataURL = function(...args) {
            toDataURLCalls += 1;
            return originalToDataURL.apply(this, args);
          };

          rendererContext.drawImage(source, 0, 0, 2, 2, 0, 0, 2, 2);
          const drawCalls = window.__bookwalkerNativeDrawCalls;
          const drawTimeToDataURLCalls = toDataURLCalls;
          sourceContext.fillStyle = 'white';
          sourceContext.fillRect(0, 0, 2, 2);
          const call = drawCalls[drawCalls.length - 1];
          const materialized = window.__bookwalkerMaterializeNativeSourceCrop({
            sourceId: call.sourceId,
            snapshotId: call.snapshotId,
            sourceConstructor: call.source.constructor,
            sourceRect: call.sourceRect,
          });
          const image = new Image();
          image.src = materialized.dataUrl;
          await image.decode();
          const probe = document.createElement('canvas');
          probe.width = 2;
          probe.height = 2;
          probe.getContext('2d').drawImage(image, 0, 0);
          const pixel = [...probe.getContext('2d').getImageData(0, 0, 1, 1).data];
          return {
            constructor: call.source.constructor,
            snapshotId: call.snapshotId,
            drawTimeToDataURLCalls,
            materializeToDataURLCalls: toDataURLCalls,
            error: materialized.error,
            pixel,
          };
        }
        """
    )

    assert result["constructor"] == "HTMLCanvasElement"
    assert result["snapshotId"]
    assert result["drawTimeToDataURLCalls"] == 0
    assert result["materializeToDataURLCalls"] == 1
    assert result["error"] is None
    assert result["pixel"][:3] == [0, 0, 0]


async def test_same_image_jpeg_and_png_have_exact_browser_signature(
    browser_page: Page,
) -> None:
    data_urls = await browser_page.evaluate(
        """
        () => {
          const canvas = document.createElement('canvas');
          canvas.width = 64;
          canvas.height = 64;
          const context = canvas.getContext('2d');
          context.fillStyle = '#ffffff';
          context.fillRect(0, 0, 64, 64);
          return {
            png: canvas.toDataURL('image/png'),
            jpeg: canvas.toDataURL('image/jpeg', 1.0),
          };
        }
        """
    )
    png_data = base64.b64decode(data_urls["png"].split(",", 1)[1])
    jpeg_data = base64.b64decode(data_urls["jpeg"].split(",", 1)[1])

    assert await image_signature(browser_page, png_data, "image/png") == await image_signature(
        browser_page, jpeg_data, "image/jpeg"
    )


async def test_retained_imagebitmap_uses_the_same_signature_contract(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    data_url = await browser_page.evaluate(
        """
        async () => {
          const canvas = document.createElement('canvas');
          canvas.width = 128;
          canvas.height = 64;
          const context = canvas.getContext('2d');
          context.fillStyle = '#ffffff';
          context.fillRect(0, 0, 128, 64);
          const bitmap = await createImageBitmap(canvas);
          window.__bookwalkerNativeSourceObjects.set('signature-bitmap', bitmap);
          return canvas.toDataURL('image/png');
        }
        """
    )
    png_data = base64.b64decode(data_url.split(",", 1)[1])

    assert await image_signature(browser_page, png_data, "image/png") == (
        await imagebitmap_signature(browser_page, "signature-bitmap")
    )


async def test_different_images_have_different_browser_signature(
    browser_page: Page,
) -> None:
    data_urls = await browser_page.evaluate(
        """
        () => {
          const make = color => {
            const canvas = document.createElement('canvas');
            canvas.width = 64;
            canvas.height = 64;
            const context = canvas.getContext('2d');
            context.fillStyle = color;
            context.fillRect(0, 0, 64, 64);
            return canvas.toDataURL('image/png');
          };
          return {white: make('#ffffff'), black: make('#000000')};
        }
        """
    )
    white = base64.b64decode(data_urls["white"].split(",", 1)[1])
    black = base64.b64decode(data_urls["black"].split(",", 1)[1])

    assert await image_signature(browser_page, white, "image/png") != await image_signature(
        browser_page, black, "image/png"
    )


async def test_completed_segment_freeze_survives_large_post_render_prefetch(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")

    trace = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 64;
          source.height = 64;
          const sourceContext = source.getContext('2d');
          sourceContext.fillStyle = '#123456';
          sourceContext.fillRect(0, 0, 64, 64);
          const bitmap = await createImageBitmap(source);

          const intermediate = document.createElement('canvas');
          intermediate.width = 64;
          intermediate.height = 64;
          const intermediateContext = intermediate.getContext('2d');
          intermediateContext.clearRect(0, 0, 64, 64);
          const tiles = [
            [0, 0, 32, 32], [32, 0, 0, 32],
            [0, 32, 32, 0], [32, 32, 0, 0],
          ];
          for (const [sx, sy, dx, dy] of tiles) {
            intermediateContext.drawImage(bitmap, sx, sy, 32, 32, dx, dy, 32, 32);
          }

          const renderer = document.createElement('canvas');
          renderer.width = 64;
          renderer.height = 64;
          renderer.getContext('2d').drawImage(intermediate, 0, 0);

          const prefetch = document.createElement('canvas');
          prefetch.width = 64;
          prefetch.height = 64;
          const prefetchContext = prefetch.getContext('2d');
          for (let index = 0; index < 6001; index += 1) {
            prefetchContext.drawImage(bitmap, 0, 0, 1, 1, 0, 0, 1, 1);
          }
          return window.__bookwalkerTransformTrace;
        }
        """
    )

    assert trace["nextOperationIndex"] > 5000
    assert "operations" not in trace
    assert len(trace["completedMappings"]) == 1
    record = trace["completedMappings"][0]
    assert record["segmentTileCount"] == 4
    assert record["segmentOverflow"] is False
    result = analyze_purchased_mapping(
        trace,
        {
            "mappingId": record["mappingId"],
            "traceOperationIndex": record["rendererOperationIndex"],
            "sourceCanvasId": record["sourceCanvas"]["canvasId"],
        },
    )
    assert result.status == MAPPING_PROVEN
    assert result.mapping is not None
    assert result.mapping.segment_tile_count == 4


async def test_selected_completed_mapping_fetch_excludes_unrelated_records(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        () => {
          window.__bookwalkerTransformTrace = {
            completedMappings: [
              {mappingId: 'unrelated-a', tileDraws: [{}, {}]},
              {mappingId: 'requested', tileDraws: [{}]},
              {mappingId: 'unrelated-b', tileDraws: [{}, {}, {}]},
              {mappingId: 'unrelated-c', tileDraws: [{}]},
            ],
            activeSegments: {
              active: {tileDraws: [{}, {}]},
            },
            droppedCompletedMappingCount: 2,
            droppedActiveSegmentCount: 1,
          };
        }
        """
    )

    selected = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_SCRIPT,
        ["requested"],
    )

    assert [record["mappingId"] for record in selected["completedMappings"]] == [
        "requested"
    ]
    assert selected["retainedCompletedMappingCount"] == 4
    assert selected["retainedCompletedTileRecordCount"] == 7
    assert selected["activeSegmentCount"] == 1
    assert selected["activeTileRecordCount"] == 2
    assert selected["requestedMappingCount"] == 1
    assert selected["returnedCompletedMappingCount"] == 1
    assert selected["returnedTileRecordCount"] == 1
    assert selected["missingMappingCount"] == 0


async def test_selected_completed_mapping_fetch_preserves_two_part_selection_order(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        () => {
          window.__bookwalkerTransformTrace = {
            completedMappings: [
              {mappingId: 'mapping-A', tileDraws: [{}]},
              {mappingId: 'mapping-B', tileDraws: [{}, {}]},
              {mappingId: 'unrelated-C', tileDraws: [{}, {}, {}]},
              {mappingId: 'unrelated-D', tileDraws: [{}]},
            ],
            activeSegments: {},
          };
        }
        """
    )

    selected = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_SCRIPT,
        ["mapping-A", "mapping-B"],
    )

    assert [record["mappingId"] for record in selected["completedMappings"]] == [
        "mapping-A",
        "mapping-B",
    ]
    assert selected["requestedMappingCount"] == 2
    assert selected["returnedCompletedMappingCount"] == 2
    assert selected["returnedTileRecordCount"] == 3
    assert selected["missingMappingCount"] == 0


async def test_selected_completed_mapping_fetch_exposes_duplicates_and_missing_ids(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        () => {
          window.__bookwalkerTransformTrace = {
            completedMappings: [
              {mappingId: 'duplicate', tileDraws: [{}]},
              {mappingId: 'duplicate', tileDraws: [{}, {}]},
            ],
            activeSegments: {},
          };
        }
        """
    )

    selected = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_SCRIPT,
        ["duplicate", "missing", "duplicate"],
    )

    assert [record["mappingId"] for record in selected["completedMappings"]] == [
        "duplicate",
        "duplicate",
    ]
    assert selected["requestedMappingCount"] == 2
    assert selected["returnedCompletedMappingCount"] == 2
    assert selected["returnedTileRecordCount"] == 3
    assert selected["missingMappingCount"] == 1

    duplicate_analysis = analyze_purchased_mapping(
        selected,
        {"mappingId": "duplicate"},
    )
    missing_analysis = analyze_purchased_mapping(
        selected,
        {"mappingId": "missing"},
    )
    assert duplicate_analysis.proven is False
    assert missing_analysis.proven is False
    assert missing_analysis.completed_mapping_evicted is True
