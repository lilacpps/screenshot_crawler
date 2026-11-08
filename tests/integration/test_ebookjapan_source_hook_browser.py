from __future__ import annotations

import base64
import io
import json

import pytest
import pytest_asyncio
from PIL import Image
from playwright.async_api import Browser, Page

from screenshot_crawler.site_adapters.ebookjapan.adapter import EbookJapanAdapter
from screenshot_crawler.site_adapters.ebookjapan.source_hook import SOURCE_OBSERVER_JS
from screenshot_crawler.site_adapters.ebookjapan.source_pixels import validate_roi_coverage
from screenshot_crawler.site_adapters.ebookjapan.viewer import CAPTURE_OBSERVER_JS

pytestmark = pytest.mark.asyncio(loop_scope="module")

READER_PATH = "/viewer/purchased/B123456789012/"
READER_URL = f"https://ebookjapan.yahoo.co.jp{READER_PATH}"


@pytest_asyncio.fixture(loop_scope="module")
async def source_page(integration_browser: Browser) -> Page:
    context = await integration_browser.new_context(viewport={"width": 1280, "height": 800})
    page = await context.new_page()
    await EbookJapanAdapter().prepare_page(page)
    await page.route(
        READER_URL,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>",
        ),
    )
    await page.goto(READER_URL)
    try:
        yield page
    finally:
        await page.close()
        await context.close()


def _webp_data_uri(width: int = 4, height: int = 2) -> str:
    image = Image.new("RGBA", (width, height))
    image.putdata(
        [
            ((x * 37) % 256, (y * 113) % 256, ((x + y) * 71) % 256, 255)
            for y in range(height)
            for x in range(width)
        ]
    )
    output = io.BytesIO()
    image.save(output, format="WEBP", lossless=True, exact=True)
    return "data:image/webp;base64," + base64.b64encode(output.getvalue()).decode("ascii")


async def _source_ready(page: Page) -> None:
    status = await page.evaluate("window.__ejSourceObserverStatus")
    assert status["installed"] is True
    assert status["routeMatches"] is True
    capture_status = await page.evaluate("window.__ejCaptureObserverStatus")
    assert capture_status["installed"] is True
    health = await page.evaluate("window.__ejSourceObserver.health()")
    assert health["nativeDescriptorsMatch"] is True


async def _draw_known_bitmap(page: Page) -> dict[str, object]:
    return await page.evaluate(
        """async sourceUrl => {
          const image=new Image();image.src=sourceUrl;await image.decode();
          const source=new OffscreenCanvas(4,2),sourceContext=source.getContext('2d');
          sourceContext.drawImage(image,0,0,2,2,0,0,2,2);
          sourceContext.drawImage(image,2,0,2,2,2,0,2,2);
          const bitmap=source.transferToImageBitmap();
          const target=document.createElement('canvas');target.width=4;target.height=2;document.body.append(target);
          target.getContext('2d').drawImage(bitmap,0,0);
          window.__ejTestSource=source;window.__ejTestSourceContext=sourceContext;
          window.__ejTestImage=image;window.__ejTestBitmap=bitmap;window.__ejTestTarget=target;
          return window.__ejSourceObserver.targetSnapshot(target);
        }""",
        _webp_data_uri(),
    )


async def _fresh_diagnostic_page(source_page: Page) -> Page:
    page = await source_page.context.new_page()
    await page.route(
        READER_URL,
        lambda route: route.fulfill(
            status=200,
            content_type="text/html",
            body="<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>",
        ),
    )
    await page.goto(READER_URL)
    return page


async def _install_diagnostic_runtime(page: Page, *, shadow: dict[str, object]) -> None:
    result = await page.evaluate(
        """({shadow,sourceHook,captureHook})=>{
          const probe=new OffscreenCanvas(1,1),prototype=Object.getPrototypeOf(probe.getContext('2d'));
          for(const name of shadow.methods||[])
            Object.defineProperty(prototype,name,{configurable:true,writable:true,value:function diagnosticShadow(){}});
          if(shadow.state){
            const descriptor=shadow.state.missing
              ?{configurable:true,get(){return 'none';},set:undefined}
              :{configurable:true,get(){return 'none';},set:function diagnosticSetter(){}};
            Object.defineProperty(prototype,shadow.state.name,descriptor);
          }
          if(shadow.privateName)
            Object.defineProperty(prototype,shadow.privateName,{configurable:true,writable:true,value:function privateDiagnosticName(){}});
          const sourceStatus=eval(sourceHook),captureStatus=eval(captureHook);
          return {sourceStatus,captureStatus};
        }""",
        {"shadow": shadow, "sourceHook": SOURCE_OBSERVER_JS, "captureHook": CAPTURE_OBSERVER_JS},
    )
    assert result["sourceStatus"]["installed"] is True
    assert result["captureStatus"]["installed"] is True


async def _run_shadow_diagnostic(source_page: Page, *, shadow: dict[str, object]) -> tuple[Page, dict[str, object]]:
    page = await _fresh_diagnostic_page(source_page)
    await _install_diagnostic_runtime(page, shadow=shadow)
    snapshot = await _draw_known_bitmap(page)
    return page, snapshot


async def test_offscreen_rois_join_transfer_to_the_existing_d_draw(source_page: Page) -> None:
    await _source_ready(source_page)
    snapshot = await _draw_known_bitmap(source_page)

    assert snapshot["binding"]["current"] is True
    assert snapshot["binding"]["reason"] == "none"
    assert snapshot["dState"]["drawGeneration"] == 1
    assert snapshot["dState"]["successfulDraws"] == 1
    source = snapshot["binding"]["source"]
    assert source["wrapperCoverageComplete"] is True
    assert source["sourceContextObjectId"] > 0
    assert source["successfulDraws"] == 2
    assert source["roiRows"] == [
        [0, 0, 2, 2, 0, 0, 2, 2],
        [2, 0, 2, 2, 2, 0, 2, 2],
    ]
    assert source["sourceImages"][0]["currentSrcPresent"] is True
    assert source["sourceImages"][0]["currentSrcUnchanged"] is True
    assert '"currentSrc":' not in json.dumps(snapshot)

    coverage = validate_roi_coverage(
        source_dimensions=(source["sourceImages"][0]["width"], source["sourceImages"][0]["height"]),
        target_dimensions=(source["width"], source["height"]),
        rois=source["roiRows"],
    )
    assert coverage.destination_coverage_complete_once is True
    assert coverage.operation_count == 2


async def test_same_dimension_canvas_reset_without_redraw_invalidates_d_and_binding(source_page: Page) -> None:
    await _draw_known_bitmap(source_page)
    snapshot = await source_page.evaluate(
        """()=>{const canvas=window.__ejTestTarget;canvas.width=canvas.width;
          return window.__ejSourceObserver.targetSnapshot(canvas);}"""
    )

    assert snapshot["binding"] is None
    assert snapshot["target"]["bindingToken"] > 0
    assert snapshot["dState"]["drawGeneration"] == 0
    assert snapshot["dState"]["resetObserved"] is True


async def test_detached_same_value_attribute_reset_invalidates_prior_binding(source_page: Page) -> None:
    await _draw_known_bitmap(source_page)
    snapshot = await source_page.evaluate(
        """()=>{const canvas=window.__ejTestTarget;canvas.remove();
          canvas.setAttribute('width',String(canvas.width));document.body.append(canvas);
          return window.__ejSourceObserver.targetSnapshot(canvas);}"""
    )

    assert snapshot["binding"] is None
    assert snapshot["dState"]["drawGeneration"] == 0
    assert snapshot["dState"]["resetObserved"] is True


async def test_a_new_transfer_makes_an_older_bitmap_binding_stale(source_page: Page) -> None:
    await _draw_known_bitmap(source_page)
    snapshot = await source_page.evaluate(
        """()=>{const source=window.__ejTestSource,image=window.__ejTestImage,ctx=window.__ejTestSourceContext;
          ctx.drawImage(image,0,0,2,2,0,0,2,2);ctx.drawImage(image,2,0,2,2,2,0,2,2);
          source.transferToImageBitmap();return window.__ejSourceObserver.targetSnapshot(window.__ejTestTarget);}"""
    )

    assert snapshot["binding"]["current"] is False
    assert snapshot["binding"]["latestTransfer"] is False
    assert snapshot["binding"]["reason"] == "source-bitmap-stale"


@pytest.mark.parametrize("mutation", ["clip", "unknown-fill", "unknown-context"])
async def test_source_clip_or_unknown_state_fails_closed(source_page: Page, mutation: str) -> None:
    snapshot = await source_page.evaluate(
        """async({sourceUrl,mutation}) => {
          if(mutation==='unknown-context'){
            const source=new OffscreenCanvas(4,2);let context=null,contextThrew=false;
            try{context=source.getContext('webgl');}catch{contextThrew=true;}
            const bitmap=source.transferToImageBitmap(),target=document.createElement('canvas');
            target.width=4;target.height=2;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
            return {result:window.__ejSourceObserver.targetSnapshot(target),contextPresent:!!context,contextThrew};
          }
          const image=new Image();image.src=sourceUrl;await image.decode();
          const source=new OffscreenCanvas(4,2),context=source.getContext('2d');
          if(mutation==='clip')context.clip();
          else if(mutation==='unknown-fill')context.fillRect(0,0,1,1);
          context.drawImage(image,0,0,2,2,0,0,2,2);context.drawImage(image,2,0,2,2,2,0,2,2);
          const bitmap=source.transferToImageBitmap();const target=document.createElement('canvas');
          target.width=4;target.height=2;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
          return {result:window.__ejSourceObserver.targetSnapshot(target)};
        }""",
        {"sourceUrl": _webp_data_uri(), "mutation": mutation},
    )

    observed = snapshot["result"]
    assert observed["binding"]["current"] is False
    assert observed["binding"]["source"]["incompleteReason"] in {
        "offscreen-clip-observed",
        "offscreen-context-type-unknown",
        "offscreen-unknown-context-method",
        "offscreen-get-context-threw",
    }
    if mutation == "unknown-context":
        assert observed["binding"]["source"]["incompleteReason"] in {
            "offscreen-context-type-unknown",
            "offscreen-get-context-threw",
        }
        assert observed["binding"]["source"]["contextKnown"] is False


@pytest.mark.parametrize("mutation", ["clip", "unknown-fill"])
@pytest.mark.parametrize("reset_kind", ["context-reset", "dimension-reset"])
async def test_source_history_survives_transfers_until_native_reset(
    source_page: Page, mutation: str, reset_kind: str
) -> None:
    result = await source_page.evaluate(
        """async({sourceUrl,mutation,resetKind}) => {
          const image=new Image();image.src=sourceUrl;await image.decode();
          const source=new OffscreenCanvas(4,2),context=source.getContext('2d'),targets=[];
          const drawAndTransfer=()=>{
            context.drawImage(image,0,0,2,2,0,0,2,2);context.drawImage(image,2,0,2,2,2,0,2,2);
            const bitmap=source.transferToImageBitmap(),target=document.createElement('canvas');
            target.width=4;target.height=2;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
            targets.push(target);return window.__ejSourceObserver.targetSnapshot(target);
          };
          if(mutation==='clip')context.clip();
          else context.fillRect(0,0,1,1);
          const first=drawAndTransfer(),second=drawAndTransfer();
          if(resetKind==='context-reset')context.reset();else source.width=source.width;
          const afterReset=drawAndTransfer();
          return {first,second,afterReset};
        }""",
        {"sourceUrl": _webp_data_uri(), "mutation": mutation, "resetKind": reset_kind},
    )

    expected_reason = "offscreen-clip-observed" if mutation == "clip" else "offscreen-unknown-context-method"
    assert result["first"]["binding"]["current"] is False
    assert result["first"]["binding"]["reason"] == expected_reason
    assert result["second"]["binding"]["current"] is False
    assert result["second"]["binding"]["reason"] == expected_reason
    assert result["second"]["binding"]["source"]["clipCount"] == (1 if mutation == "clip" else 0)
    assert result["afterReset"]["binding"]["current"] is True
    assert result["afterReset"]["binding"]["source"]["clipCount"] == 0


async def test_get_context_coercion_runs_once_and_exception_identity_is_preserved(source_page: Page) -> None:
    result = await source_page.evaluate(
        """()=>{
          const source=new OffscreenCanvas(2,2);let coercions=0;
          const context=source.getContext({[Symbol.toPrimitive](){coercions++;return '2d';}});
          const bitmap=source.transferToImageBitmap(),target=document.createElement('canvas');
          target.width=2;target.height=2;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
          const snapshot=window.__ejSourceObserver.targetSnapshot(target),sentinel={};let throws=0,caught=null;
          try{new OffscreenCanvas(1,1).getContext({[Symbol.toPrimitive](){throws++;throw sentinel;}});}catch(error){caught=error;}
          return {coercions,contextBound:context.canvas===source,snapshot,throws,exceptionIdentity:caught===sentinel};
        }"""
    )

    assert result["coercions"] == 1
    assert result["contextBound"] is True
    assert result["snapshot"]["binding"]["current"] is False
    assert result["snapshot"]["binding"]["reason"] == "offscreen-context-type-unknown"
    assert result["throws"] == 1
    assert result["exceptionIdentity"] is True


@pytest.mark.parametrize("replace_width_setter", [False, True])
async def test_stop_restores_owned_descriptors_without_overwriting_later_changes(
    source_page: Page, replace_width_setter: bool
) -> None:
    result = await source_page.evaluate(
        """replaceWidthSetter=>{
          const proto=OffscreenCanvas.prototype,descriptor=Object.getOwnPropertyDescriptor(proto,'width');
          let replacementSetter=null;
          if(replaceWidthSetter){
            replacementSetter=function(value){return Reflect.apply(descriptor.set,this,[value]);};
            Object.defineProperty(proto,'width',{...descriptor,set:replacementSetter});
          }
          const stopped=window.__ejSourceObserver.stop(),current=Object.getOwnPropertyDescriptor(proto,'width');
          return {stopped,widthSetterStillOwnedByOther:!!replacementSetter&&current.set===replacementSetter,
            widthRestored:stopped.restored.width,heightRestored:stopped.restored.height,
            transferRestored:stopped.restored.transferToImageBitmap};
        }""",
        replace_width_setter,
    )

    if replace_width_setter:
        assert result["widthSetterStillOwnedByOther"] is True
        assert result["widthRestored"] is False
        assert result["heightRestored"] is True
        assert result["transferRestored"] is True
    else:
        assert result["widthSetterStillOwnedByOther"] is False
        assert result["widthRestored"] is True
        assert result["heightRestored"] is True
        assert result["transferRestored"] is True


async def test_non_default_canvas_filter_is_redacted_and_ineligible(source_page: Page) -> None:
    result = await source_page.evaluate(
        """async sourceUrl=>{
          const image=new Image();image.src=sourceUrl;await image.decode();
          const secret='url(#private-filter-marker)',source=new OffscreenCanvas(4,2),context=source.getContext('2d');
          context.filter=secret;
          const actualFilter=context.filter;
          context.drawImage(image,0,0,2,2,0,0,2,2);context.drawImage(image,2,0,2,2,2,0,2,2);
          const bitmap=source.transferToImageBitmap(),target=document.createElement('canvas');
          target.width=4;target.height=2;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
          return {actualFilter,snapshot:window.__ejSourceObserver.targetSnapshot(target)};
        }""",
        _webp_data_uri(),
    )

    assert result["actualFilter"] != "none"
    assert "private-filter-marker" not in json.dumps(result["snapshot"])
    assert result["snapshot"]["binding"]["current"] is False
    assert result["snapshot"]["binding"]["source"]["incompleteReason"] == "offscreen-context-state-mutated"
    assert result["snapshot"]["binding"]["source"]["drawState"]["filterValue"] == "non-default"


async def test_epoch_budget_evicts_old_targets_and_keeps_latest_current(source_page: Page) -> None:
    await _source_ready(source_page)
    result = await source_page.evaluate(
        """async sourceUrl => {
          const image=new Image();image.src=sourceUrl;await image.decode();
          const source=new OffscreenCanvas(32,16),context=source.getContext('2d'),targets=[];
          for(let index=0;index<100;index++){
            for(let y=0;y<16;y++)for(let x=0;x<16;x++)
              context.drawImage(image,x*2,y,2,1,x*2,y,2,1);
            const bitmap=source.transferToImageBitmap(),target=document.createElement('canvas');
            target.width=32;target.height=16;document.body.append(target);target.getContext('2d').drawImage(bitmap,0,0);
            targets.push(target);
          }
          return {first:window.__ejSourceObserver.targetSnapshot(targets[0]),
            last:window.__ejSourceObserver.targetSnapshot(targets[99]),health:window.__ejSourceObserver.health(),
            dHealth:window.__ejCaptureObserver.health()};
        }""",
        _webp_data_uri(32, 16),
    )

    assert result["health"]["activeEpochs"] == 32
    assert result["health"]["cacheEvictions"] == 68
    assert result["first"]["binding"]["current"] is False
    assert result["first"]["binding"]["reason"] == "source-epoch-evicted"
    assert result["last"]["binding"]["current"] is True
    assert result["last"]["binding"]["source"]["successfulDraws"] == 256
    assert result["dHealth"]["overflow"] is False


@pytest.mark.parametrize(
    ("method_name", "diagnostic_bucket"),
    [("arc", "offscreenMethodNonNative"), ("getImageData", "offscreenMethodNonNative")],
)
async def test_unused_method_shadow_is_reported_without_relaxing_current_proof(
    source_page: Page, method_name: str, diagnostic_bucket: str
) -> None:
    page, snapshot = await _run_shadow_diagnostic(source_page, shadow={"methods": [method_name]})
    try:
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        assert snapshot["binding"]["current"] is False
        assert diagnostic["offscreenInstall"] is False
        assert method_name in diagnostic[diagnostic_bucket]
    finally:
        await page.close()


@pytest.mark.parametrize("method_name", ["drawImage", "clip"])
async def test_critical_method_shadow_is_reported_and_keeps_proof_unknown(
    source_page: Page, method_name: str
) -> None:
    page, snapshot = await _run_shadow_diagnostic(source_page, shadow={"methods": [method_name]})
    try:
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        assert snapshot["binding"]["current"] is False
        assert diagnostic["offscreenInstall"] is False
        assert method_name in diagnostic["offscreenMethodNonNative"]
    finally:
        await page.close()


@pytest.mark.parametrize("method_name", ["measureText", "createPattern", "scrollPathIntoView"])
async def test_standard_canvas_method_shadow_is_allowlisted_and_keeps_proof_unknown(
    source_page: Page, method_name: str
) -> None:
    page, snapshot = await _run_shadow_diagnostic(source_page, shadow={"methods": [method_name]})
    try:
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        assert snapshot["binding"]["current"] is False
        assert diagnostic["offscreenInstall"] is False
        assert method_name in diagnostic["offscreenMethodNonNative"]
        assert diagnostic["otherMethodCount"] == 0
    finally:
        await page.close()


@pytest.mark.parametrize("missing", [False, True])
async def test_state_setter_diagnostic_reports_only_fixed_property_names(
    source_page: Page, missing: bool
) -> None:
    page, snapshot = await _run_shadow_diagnostic(
        source_page, shadow={"state": {"name": "filter", "missing": missing}}
    )
    try:
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        assert snapshot["binding"]["current"] is False
        assert diagnostic["offscreenInstall"] is False
        bucket = "offscreenStateSetterMissing" if missing else "offscreenStateSetterNonNative"
        assert "filter" in diagnostic[bucket]
    finally:
        await page.close()


@pytest.mark.parametrize("method_name", ["getImageData", "measureText", "createPattern"])
async def test_later_wrapper_change_is_reported_as_a_safe_slot_mismatch(
    source_page: Page, method_name: str
) -> None:
    page, _snapshot = await _run_shadow_diagnostic(source_page, shadow={})
    try:
        snapshot = await page.evaluate(
            """methodName=>{
              const prototype=CanvasRenderingContext2D.prototype;
              Object.defineProperty(prototype,methodName,{configurable:true,writable:true,value:function replacedSlot(){}});
              return window.__ejSourceObserver.targetSnapshot(window.__ejTestTarget);
            }""",
            method_name,
        )
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        assert snapshot["binding"]["current"] is False
        assert diagnostic["currentSlotMismatch"] is True
        assert method_name in diagnostic["slotMismatchMethods"]
        assert diagnostic["otherMethodCount"] == 0
    finally:
        await page.close()


async def test_unknown_shadow_name_is_counted_but_never_returned(source_page: Page) -> None:
    private_name = "privateSecretDiagnosticSlot_7d3b"
    page, snapshot = await _run_shadow_diagnostic(source_page, shadow={"privateName": private_name})
    try:
        diagnostic = snapshot["health"]["instrumentationDiagnostic"]
        encoded = json.dumps(diagnostic)
        assert snapshot["binding"]["current"] is False
        assert diagnostic["otherMethodCount"] >= 1
        assert private_name not in encoded
    finally:
        await page.close()
