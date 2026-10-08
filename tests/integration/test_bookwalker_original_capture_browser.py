from __future__ import annotations

import base64

import pytest
from playwright.async_api import Page

from screenshot_crawler.site_adapters.bookwalker import adapter as adapter_module
from screenshot_crawler.site_adapters.bookwalker.adapter import (
    _SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT,
    _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
    BookWalkerAdapter,
)
from screenshot_crawler.site_adapters.bookwalker.original_capture import (
    image_signature,
    imagebitmap_signature,
)
from screenshot_crawler.site_adapters.bookwalker.purchased_mapping import (
    MAPPING_PROVEN,
    analyze_purchased_mapping,
    decode_compact_completed_mappings,
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


def _completed_mapping_fixture(mapping_id: str, renderer_index: int) -> dict[str, object]:
    source_id = f"bitmap-{mapping_id}"
    tiles = []
    for offset, (source_x, source_y, destination_x, destination_y) in enumerate(
        ((0, 0, 16, 0), (16, 0, 0, 0), (0, 16, 0, 16), (16, 16, 16, 16)),
        start=102,
    ):
        tiles.append(
            {
                "operationIndex": offset,
                "source": {
                    "sourceId": source_id,
                    "constructor": "ImageBitmap",
                    "width": 32,
                    "height": 32,
                },
                "target": {"canvasId": "source-canvas", "width": 32, "height": 32},
                "sourceRect": {"x": source_x, "y": source_y, "width": 16, "height": 16},
                "destination": {
                    "x": destination_x,
                    "y": destination_y,
                    "width": 16,
                    "height": 16,
                },
                "transform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
                "globalAlpha": 1,
                "globalCompositeOperation": "source-over",
                "filter": "none",
            }
        )
    return {
        "mappingId": mapping_id,
        "rendererOperationIndex": renderer_index,
        "rendererTarget": {"canvasId": "renderer", "width": 32, "height": 32},
        "sourceCanvas": {"canvasId": "source-canvas", "width": 32, "height": 32},
        "rendererSourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererDestination": {"x": 0, "y": 0, "width": 32, "height": 32},
        "rendererTransform": {"a": 1, "b": 0, "c": 0, "d": 1, "e": 0, "f": 0},
        "rendererAlpha": 1,
        "rendererComposite": "source-over",
        "rendererFilter": "none",
        "segmentClearOperationIndex": 101,
        "segmentClearRectangle": {"x": 0, "y": 0, "width": 32, "height": 32},
        "segmentFirstTileOperationIndex": 102,
        "segmentLastTileOperationIndex": 105,
        "segmentTileCount": 4,
        "segmentExpectedTileCount": 4,
        "tileDraws": tiles,
        "sourceIds": [source_id],
        "unsafeOperationCount": 0,
        "firstUnsafeOperationIndex": None,
        "unsafeOperationTypes": [],
        "segmentOverflow": False,
    }


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


async def test_dimension_reset_epoch_and_cropped_one_hop_snapshots_are_recorded(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script("window.__bookwalkerCaptureMode = 'native';")
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const bitmapSource = document.createElement('canvas');
          bitmapSource.width = 24; bitmapSource.height = 16;
          const sourceContext = bitmapSource.getContext('2d');
          sourceContext.fillStyle = 'rgb(20,40,60)'; sourceContext.fillRect(0, 0, 24, 16);
          const bitmap = await createImageBitmap(bitmapSource);
          const tileCanvas = document.createElement('canvas');
          tileCanvas.width = 17; tileCanvas.height = 16;
          const tileContext = tileCanvas.getContext('2d');
          const positions = [[0,0],[8,0],[16,0],[0,8],[8,8],[16,8]];
          for (const [x, y] of positions) {
            tileContext.drawImage(bitmap, x, y, 8, 8, x, y, 8, 8);
          }
          // A same-value setter is still a destructive reset boundary.
          tileCanvas.width = 17;
          tileCanvas.height = 16;
          for (const [x, y] of positions) {
            tileContext.drawImage(bitmap, x, y, 8, 8, x, y, 8, 8);
          }
          const intermediate = document.createElement('canvas');
          intermediate.width = 8; intermediate.height = 8;
          intermediate.getContext('2d').drawImage(tileCanvas, 0, 0, 17, 16, 0, 0, 8, 8);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(intermediate, 0, 0, 8, 8, 10, 10, 8, 8);
          await new Promise(resolve => setTimeout(resolve, 0));
          const trace = window.__bookwalkerTransformTrace;
          const completed = trace.completedMappings || [];
          const mapping = completed.find(item => item.sourceCanvas?.width === 17);
          const calls = window.__bookwalkerNativeDrawCalls || [];
          const call = calls[calls.length - 1];
          const unknownCanvas = document.createElement('canvas');
          unknownCanvas.width = 4; unknownCanvas.height = 4;
          unknownCanvas.setAttribute('width', '5');
          const internalCanvas = document.createElement('canvas');
          window.__bookwalkerMarkInternalCanvas(internalCanvas);
          internalCanvas.width = 4; internalCanvas.height = 4;
          internalCanvas.setAttribute('width', '5');
          await new Promise(resolve => setTimeout(resolve, 0));
          return {
            resetObserved: trace.diagnostics.canvasResetObservationAvailable,
            unknownMutations: trace.diagnostics.unknownCanvasMutationCount,
            mapping: mapping ? {
              resetKind: mapping.segmentResetKind,
              resetEpoch: mapping.segmentResetEpoch,
              clearTarget: mapping.segmentClearTarget,
              drawTarget: mapping.segmentDrawTarget,
              resetObservationAvailable: mapping.segmentResetObservationAvailable,
              mutationObserverAvailable: mapping.segmentMutationObserverAvailable,
              mutationObserverTakeRecordsAvailable:
                mapping.segmentMutationObserverTakeRecordsAvailable,
              tileCount: mapping.segmentTileCount,
            } : null,
            native: call ? {
              fullSourceSnapshotId: call.fullSourceSnapshotId || null,
              targetSnapshotId: call.targetSnapshotId || null,
              sourceRect: call.sourceRect,
              destination: call.destination,
            } : null,
            resetEpochs: completed.filter(item => item.sourceCanvas?.width === 17)
              .map(item => item.segmentResetEpoch),
          };
        }
        """
    )
    assert result["resetObserved"] is True
    assert result["unknownMutations"] >= 1
    assert result["mapping"]["resetKind"] == "canvas_dimension_reset"
    assert result["mapping"]["resetEpoch"] is not None
    assert result["mapping"]["clearTarget"]["width"] == 17
    assert result["mapping"]["drawTarget"]["width"] == 17
    assert result["mapping"]["resetObservationAvailable"] is True
    assert result["mapping"]["mutationObserverAvailable"] is True
    assert result["mapping"]["mutationObserverTakeRecordsAvailable"] is True
    assert result["mapping"]["tileCount"] == 6
    assert max(result["resetEpochs"]) >= 3
    assert result["native"]["fullSourceSnapshotId"]
    assert result["native"]["targetSnapshotId"]


@pytest.mark.parametrize("failure_mode", ["partial_setter", "observer_unavailable"])
async def test_cropped_reset_proof_fails_closed_when_observation_is_incomplete(
    browser_page: Page,
    failure_mode: str,
) -> None:
    if failure_mode == "partial_setter":
        await browser_page.add_init_script(
            """
            (() => {
              const descriptor = Object.getOwnPropertyDescriptor(
                HTMLCanvasElement.prototype, 'height');
              Object.defineProperty(HTMLCanvasElement.prototype, 'height', {
                configurable: false,
                enumerable: descriptor.enumerable,
                get: descriptor.get,
                set: descriptor.set,
              });
            })();
            """
        )
    else:
        await browser_page.add_init_script(
            "Object.defineProperty(window, 'MutationObserver', {value: undefined, configurable: true});"
        )
    await browser_page.add_init_script("window.__bookwalkerCaptureMode = 'native';")
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 8; source.height = 8;
          source.getContext('2d').fillRect(0, 0, 8, 8);
          const bitmap = await createImageBitmap(source);
          const tiled = document.createElement('canvas');
          tiled.width = 8; tiled.height = 8;
          tiled.getContext('2d').drawImage(bitmap, 0, 0, 8, 8, 0, 0, 8, 8);
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(tiled, 0, 0, 8, 8, 0, 0, 8, 8);
          await new Promise(resolve => setTimeout(resolve, 0));
          const trace = window.__bookwalkerTransformTrace;
          const mapping = (trace.completedMappings || [])
            .find(item => item.sourceCanvas?.width === 8);
          return {
            hooks: trace.diagnostics.canvasResetObservationAvailable,
            mapping: mapping ? {
              resetObservationAvailable: mapping.segmentResetObservationAvailable,
              mutationObserverAvailable: mapping.segmentMutationObserverAvailable,
              mutationObserverTakeRecordsAvailable:
                mapping.segmentMutationObserverTakeRecordsAvailable,
            } : null,
          };
        }
        """
    )
    assert result["hooks"] is (failure_mode != "partial_setter")
    assert result["mapping"] is not None
    assert result["mapping"]["resetObservationAvailable"] is False
    assert result["mapping"]["mutationObserverAvailable"] is (
        failure_mode != "observer_unavailable"
    )
    assert result["mapping"]["mutationObserverTakeRecordsAvailable"] is (
        failure_mode != "observer_unavailable"
    )


async def test_same_task_canvas_attribute_mutation_is_flushed_before_mapping_freeze(
    browser_page: Page,
) -> None:
    await browser_page.add_init_script("window.__bookwalkerCaptureMode = 'native';")
    await browser_page.add_init_script(adapter_module._DRAW_TRACE_SCRIPT)
    await browser_page.goto("data:text/html,<html><body></body></html>")
    result = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 8; source.height = 8;
          source.getContext('2d').fillRect(0, 0, 8, 8);
          const bitmap = await createImageBitmap(source);
          const tiled = document.createElement('canvas');
          tiled.width = 8; tiled.height = 8;
          tiled.getContext('2d').drawImage(bitmap, 0, 0, 8, 8, 0, 0, 8, 8);
          // The mutation and selected renderer draw happen in the same task.
          tiled.setAttribute('width', '8');
          const renderer = document.createElement('canvas');
          renderer.width = 1200; renderer.height = 600;
          renderer.getContext('2d').drawImage(tiled, 0, 0, 8, 8, 0, 0, 8, 8);
          const trace = window.__bookwalkerTransformTrace;
          const mapping = (trace.completedMappings || [])
            .find(item => item.sourceCanvas?.width === 8);
          return {
            unknownCount: trace.diagnostics.unknownCanvasMutationCount,
            unknown: mapping?.segmentUnknownMutation === true,
          };
        }
        """
    )
    assert result["unknownCount"] >= 1
    assert result["unknown"] is True


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


async def test_scaled_source_diagnostic_reproduces_observed_full_frame_scale(
    browser_page: Page,
) -> None:
    source_and_native = await browser_page.evaluate(
        """
        async () => {
          const source = document.createElement('canvas');
          source.width = 32;
          source.height = 32;
          const sourceContext = source.getContext('2d');
          for (let y = 0; y < 32; y += 1) {
            for (let x = 0; x < 32; x += 1) {
              sourceContext.fillStyle = `rgb(${x * 8}, ${y * 8}, ${(x + y) * 4})`;
              sourceContext.fillRect(x, y, 1, 1);
            }
          }
          const reconstructed = source.toDataURL('image/jpeg', 1.0);
          const image = await createImageBitmap(
            await (await fetch(reconstructed)).blob(),
          );
          const target = document.createElement('canvas');
          target.width = 16;
          target.height = 16;
          const targetContext = target.getContext('2d');
          targetContext.imageSmoothingEnabled = true;
          targetContext.imageSmoothingQuality = 'high';
          targetContext.drawImage(image, 0, 0, 32, 32, 0, 0, 16, 16);
          image.close();
          return {reconstructed, native: target.toDataURL('image/png')};
        }
        """
    )
    result = await browser_page.evaluate(
        _SCALED_SOURCE_PIXEL_EXACT_COMPARISON_SCRIPT,
        {
            **source_and_native,
            "sourceRect": {"x": 0, "y": 0, "width": 32, "height": 32},
            "destination": {"x": 0, "y": 0, "width": 16, "height": 16},
            "targetDimensions": {"width": 16, "height": 16},
            "imageSmoothingEnabled": True,
            "imageSmoothingQuality": "high",
        },
    )

    assert result["available"] is True
    assert result["exact"] is True
    assert result["differing_pixel_count"] == 0
    assert result["max_channel_difference"] == 0


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

    compact_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        [record["mappingId"]],
    )
    decoded = decode_compact_completed_mappings(compact_payload)
    assert decoded is not None
    compact_result = analyze_purchased_mapping(
        decoded,
        {
            "mappingId": record["mappingId"],
            "traceOperationIndex": record["rendererOperationIndex"],
            "sourceCanvasId": record["sourceCanvas"]["canvasId"],
        },
    )
    assert compact_result.to_debug() == result.to_debug()


async def test_selected_completed_mapping_fetch_excludes_unrelated_records(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {
            completedMappings,
            activeSegments: {active: {tileDraws: [{}, {}]}},
            droppedCompletedMappingCount: 2,
            droppedActiveSegmentCount: 1,
          };
        }
        """,
        [
            _completed_mapping_fixture("unrelated-a", 106),
            _completed_mapping_fixture("requested", 206),
            _completed_mapping_fixture("unrelated-b", 306),
            _completed_mapping_fixture("unrelated-c", 406),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["requested"],
    )

    assert selected_payload["transportVersion"] == 1
    assert "completedMappings" not in selected_payload
    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "requested"
    ]
    assert selected_payload["retainedCompletedMappingCount"] == 4
    assert selected_payload["retainedCompletedTileRecordCount"] == 16
    assert selected_payload["activeSegmentCount"] == 1
    assert selected_payload["activeTileRecordCount"] == 2
    assert selected_payload["requestedMappingCount"] == 1
    assert selected_payload["returnedCompletedMappingCount"] == 1
    assert selected_payload["returnedTileRecordCount"] == 4
    assert selected_payload["missingMappingCount"] == 0
    assert selected_payload["compactSourceTableCount"] == 1
    assert selected_payload["compactTargetTableCount"] == 1
    assert selected_payload["compactTransformTableCount"] == 1
    assert selected_payload["compactCompositeTableCount"] == 1
    assert selected_payload["compactFilterTableCount"] == 1
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None
    assert [record["mappingId"] for record in decoded["completedMappings"]] == [
        "requested"
    ]


async def test_selected_completed_mapping_fetch_preserves_two_part_selection_order(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {completedMappings, activeSegments: {}};
        }
        """,
        [
            _completed_mapping_fixture("mapping-A", 106),
            _completed_mapping_fixture("mapping-B", 206),
            _completed_mapping_fixture("unrelated-C", 306),
            _completed_mapping_fixture("unrelated-D", 406),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["mapping-A", "mapping-B"],
    )

    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "mapping-A",
        "mapping-B",
    ]
    assert selected_payload["requestedMappingCount"] == 2
    assert selected_payload["returnedCompletedMappingCount"] == 2
    assert selected_payload["returnedTileRecordCount"] == 8
    assert selected_payload["missingMappingCount"] == 0
    assert selected_payload["compactSourceTableCount"] == 2
    assert selected_payload["compactTargetTableCount"] == 2
    assert selected_payload["compactTransformTableCount"] == 2
    assert selected_payload["compactCompositeTableCount"] == 2
    assert selected_payload["compactFilterTableCount"] == 2
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None
    assert [record["mappingId"] for record in decoded["completedMappings"]] == [
        "mapping-A",
        "mapping-B",
    ]
    for record in decoded["completedMappings"]:
        analysis = analyze_purchased_mapping(
            decoded,
            {
                "mappingId": record["mappingId"],
                "traceOperationIndex": record["rendererOperationIndex"],
                "sourceCanvasId": record["sourceCanvas"]["canvasId"],
            },
        )
        assert analysis.proven


async def test_selected_completed_mapping_fetch_exposes_duplicates_and_missing_ids(
    browser_page: Page,
) -> None:
    await browser_page.goto("data:text/html,<html><body></body></html>")
    await browser_page.evaluate(
        """
        (completedMappings) => {
          window.__bookwalkerTransformTrace = {completedMappings, activeSegments: {}};
        }
        """,
        [
            _completed_mapping_fixture("duplicate", 106),
            _completed_mapping_fixture("duplicate", 206),
        ],
    )

    selected_payload = await browser_page.evaluate(
        _SELECTED_COMPLETED_MAPPINGS_COMPACT_SCRIPT,
        ["duplicate", "missing", "duplicate"],
    )

    assert [record["mappingId"] for record in selected_payload["compactMappings"]] == [
        "duplicate",
        "duplicate",
    ]
    assert selected_payload["requestedMappingCount"] == 2
    assert selected_payload["returnedCompletedMappingCount"] == 2
    assert selected_payload["returnedTileRecordCount"] == 8
    assert selected_payload["missingMappingCount"] == 1
    decoded = decode_compact_completed_mappings(selected_payload)
    assert decoded is not None

    duplicate_analysis = analyze_purchased_mapping(
        decoded,
        {"mappingId": "duplicate"},
    )
    missing_analysis = analyze_purchased_mapping(
        decoded,
        {"mappingId": "missing"},
    )
    assert duplicate_analysis.proven is False
    assert missing_analysis.proven is False
    assert missing_analysis.completed_mapping_evicted is True
