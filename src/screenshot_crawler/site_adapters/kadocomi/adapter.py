"""Fail-closed native WebP capture for Kadocomi's observed WEB reader."""

from __future__ import annotations

import asyncio
import base64
import math
import re
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page, Response

from screenshot_crawler.core.access_guard import AccessProfile
from screenshot_crawler.core.capture import CaptureResult
from screenshot_crawler.core.errors import (
    PageChangeTimeoutError,
    UnknownPageStateError,
    UnsupportedAccessStrategyError,
)
from screenshot_crawler.core.models import AccessStrategy, ContentContext, ContentIdentity
from screenshot_crawler.core.state import PageState
from screenshot_crawler.site_adapters.base import SiteAdapter
from screenshot_crawler.site_adapters.kadocomi.access import kadocomi_access_profile
from screenshot_crawler.site_adapters.kadocomi.discovery import (
    canonical_kadocomi_episode_url,
    parse_kadocomi_episode_url,
)
from screenshot_crawler.site_adapters.kadocomi.native_capture import (
    MAX_NATIVE_BLOB_BYTES,
    MAX_NATIVE_PIXEL_COUNT,
    MAX_NATIVE_TOTAL_PIXEL_COUNT,
    NATIVE_CAPTURE_SCRIPT,
    NATIVE_OBSERVER_INIT_SCRIPT,
    capture_kadocomi_webp,
)

INITIALIZE_TIMEOUT_MS = 90_000
VIEWER_READY_TIMEOUT_SECONDS = 35.0
METADATA_READY_TIMEOUT_SECONDS = 10.0
VIEWER_POLL_MS = 150
PAGE_CHANGE_TIMEOUT_SECONDS = 12.0
MAX_CANVAS_SLOTS = 500
_PAIRED_END_LAYOUT = "paired_end"
_MIXED_FINAL_END_LAYOUT = "mixed_final_end"
_BEGINNING_PR_PAIRED_LAYOUT = "beginning_pr_paired"
_BEGINNING_PR_MIXED_FINAL_LAYOUT = "beginning_pr_mixed_final"
_BEGINNING_PR_FINAL_PR_LAYOUT = "beginning_pr_final_pr"
_CONTENT_FIRST_FINAL_PR_LAYOUT = "content_first_final_pr"
_PAIRED_FIRST_DOUBLE_END_LAYOUT = "paired_first_double_end"
_PAIRED_FIRST_FINAL_PR_LAYOUT = "paired_first_final_pr"
_PAIRED_FIRST_PR_END_LAYOUT = "paired_first_pr_end"
_DIRECT_FIRST_FINAL_PR_LAYOUT = "direct_first_final_pr"
_DIRECT_FIRST_PR_END_LAYOUT = "direct_first_pr_end"
_DIRECT_FIRST_LAYOUTS = {_DIRECT_FIRST_FINAL_PR_LAYOUT, _DIRECT_FIRST_PR_END_LAYOUT}
_PR_END_LAYOUTS = {_PAIRED_FIRST_PR_END_LAYOUT, _DIRECT_FIRST_PR_END_LAYOUT}
_TRACKED_PR_LAYOUTS = {
    _CONTENT_FIRST_FINAL_PR_LAYOUT, _PAIRED_FIRST_DOUBLE_END_LAYOUT,
    _PAIRED_FIRST_FINAL_PR_LAYOUT, _PAIRED_FIRST_PR_END_LAYOUT,
    *_DIRECT_FIRST_LAYOUTS,
}
_EXTERNAL_ID = re.compile(r"^(?P<work>KC_[0-9]{6}_S):(?P<episode>KC_[0-9]{16}_E)$")
_EPISODE_HEADING = re.compile(r"^\u3010(?P<order>[^\u3011]+)\u3011(?P<work>.+)$")
_OG_TITLE_SUFFIX = "\uFF5C\u30AB\u30C9\u30B3\u30DF (\u30B3\u30DF\u30C3\u30AF\u30A6\u30A9\u30FC\u30AB\u30FC)"

_READ_EPISODE_METADATA_SCRIPT = r"""() => {
  const normalize = value => (value || '').replace(/\s+/g, ' ').trim();
  const headings = [...document.querySelectorAll('h1')].filter(node =>
    node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden');
  const titles = [...document.querySelectorAll('meta[property="og:title"]')]
    .map(node => node.content || '');
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')]
    .filter(node => node.getClientRects().length > 0 &&
      getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none');
  return {
    headingCount: headings.length,
    heading: headings.length === 1 ? normalize(headings[0].innerText) : null,
    titleCount: titles.length,
    ogTitle: titles.length === 1 ? normalize(titles[0]) : null,
    documentTitle: normalize(document.title),
    visibleDialogCount: dialogs.length
  };
}"""

_NAVIGATION_TARGET_SCRIPT = r"""() => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (active.length !== 1 || active[0].classList.contains('splide__slide--clone'))
    return {ok: false, reason: 'active_slide'};
  const typedContent = [...active[0].querySelectorAll('[data-type="contents"]')];
  const wrappers = typedContent.filter(node => node.tagName === 'DIV' &&
    [...node.classList].some(name => name.startsWith('_pageCanvasWrapper_')));
  if (wrappers.length !== typedContent.length ||
      wrappers.some(wrapper => {
        const canvases = [...wrapper.querySelectorAll('canvas')];
        return canvases.length !== 1 ||
          ![...canvases[0].classList].some(name => name.startsWith('_root_bx4cr_'));
      }))
    return {ok: false, reason: 'content_wrapper_shape'};
  const rootRect = root.getBoundingClientRect();
  if (rootRect.width <= 0 || rootRect.height <= 0) return {ok: false, reason: 'root_geometry'};
  const covers = [...active[0].querySelectorAll('._cover_bx4cr_11')]
    .filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 &&
        getComputedStyle(node).visibility !== 'hidden' &&
        getComputedStyle(node).display !== 'none';
    }).map(node => ({node, rect: node.getBoundingClientRect()}))
    .sort((left, right) => left.rect.left - right.rect.left);
  if (!covers.length) return {ok: false, reason: 'left_overlay_missing'};
  const viewportLeft = Math.max(0, rootRect.left);
  const viewportRight = Math.min(innerWidth, rootRect.right);
  const viewportTop = Math.max(0, rootRect.top);
  const viewportBottom = Math.min(innerHeight, rootRect.bottom);
  const targetY = (viewportTop + viewportBottom) / 2;
  for (const candidate of covers) {
    const left = Math.max(candidate.rect.left, viewportLeft);
    const right = Math.min(candidate.rect.right, viewportRight);
    const top = Math.max(candidate.rect.top, viewportTop);
    const bottom = Math.min(candidate.rect.bottom, viewportBottom);
    if (right <= left || bottom <= top || targetY < top || targetY > bottom) continue;
    const x = left + Math.min(2, (right - left) / 4);
    const y = targetY;
    const hit = document.elementFromPoint(x, y);
    const hitCover = hit && (hit === candidate.node || candidate.node.contains(hit));
    const hitActive = hit && hit.closest('.splide__slide') === active[0];
    if (hitCover && hitActive) return {
      ok: true, x, y, activeIndex: slides.indexOf(active[0]),
      slotCount: wrappers.length
    };
  }
  return {ok: false, reason: 'left_overlay_hit_test_failed'};
}"""

_MIXED_FINAL_ARROW_SAFE_SCRIPT = r"""args => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  if (!root.classList.contains('splide--rtl')) return {ok: false, reason: 'rtl_class'};
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (active.length !== 1 || slides.indexOf(active[0]) !== args.activeIndex)
    return {ok: false, reason: 'active_slide'};
  const canvases = [...active[0].querySelectorAll('div[data-type="contents"]')]
    .filter(node => [...node.classList].some(name => name.startsWith('_pageCanvasWrapper_')));
  if (canvases.length !== 1 || canvases.length !== args.slotCount)
    return {ok: false, reason: 'final_content_shape'};
  const terminalMarker = [...active[0].querySelectorAll('div[data-type="end-of-book"][data-n="2"]')]
    .filter(node => [...node.classList].some(name => name.startsWith('_endOfBookWrapper_')));
  if (terminalMarker.length !== 1) return {ok: false, reason: 'final_end_marker'};
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')]
    .filter(node => node.getClientRects().length > 0 &&
      getComputedStyle(node).visibility !== 'hidden' && getComputedStyle(node).display !== 'none');
  if (dialogs.length) return {ok: false, reason: 'visible_dialog'};
  const focus = document.activeElement;
  if (focus !== document.body && focus !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: slides.indexOf(active[0]), slotCount: canvases.length};
}"""

_BEGINNING_PR_ARROW_SAFE_SCRIPT = r"""() => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  if (!root.classList.contains('splide--rtl')) return {ok: false, reason: 'rtl_class'};
  const visibleInViewport = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < innerWidth && rect.top < innerHeight;
  };
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (!visibleInViewport(root) || active.length !== 1 || slides.indexOf(active[0]) !== 0 ||
      !visibleInViewport(active[0]))
    return {ok: false, reason: 'active_slide'};
  const begins = [...root.querySelectorAll('div[data-type="beginning"]')];
  const prs = [...root.querySelectorAll('div[data-type="pr"]')];
  const prefix = (node, value) => [...node.classList].some(name => name.startsWith(value));
  if (begins.length !== 1 || prs.length !== 1 || begins[0].closest('.splide__slide') !== active[0] ||
      !prefix(begins[0], '_root_1w5tt_') || prs[0].closest('div[data-type="beginning"]') !== begins[0] ||
      prs[0].closest('.splide__slide') !== active[0] || !prefix(prs[0], '_endOfBook_') ||
      prefix(prs[0], '_endOfBookWrapper_') || prs[0].getAttribute('data-n') !== null ||
      active[0].querySelectorAll('div[data-type="contents"]').length !== 0 || slides.length < 3 ||
      slides[1].querySelectorAll('div[data-type="contents"]').length !== 2)
    return {ok: false, reason: 'beginning_pr_shape'};
  const contained = node => {
    const owner = node.closest('.splide__slide');
    const r = node.getBoundingClientRect(), sr = owner.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && sr.width > 0 && sr.height > 0 &&
      r.left >= sr.left - 1 && r.top >= sr.top - 1 &&
      r.right <= sr.right + 1 && r.bottom <= sr.bottom + 1;
  };
  if (!contained(begins[0]) || !contained(prs[0]) ||
      !visibleInViewport(begins[0]) || !visibleInViewport(prs[0]))
    return {ok: false, reason: 'beginning_pr_geometry'};
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')].filter(node => {
    const r = node.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(node).visibility !== 'hidden' &&
      getComputedStyle(node).display !== 'none';
  });
  if (dialogs.length) return {ok: false, reason: 'visible_dialog'};
  const focus = document.activeElement;
  if (focus !== document.body && focus !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: 0, focusTag: focus.tagName};
}""";

_BEGINNING_PR_FINAL_PR_ARROW_SAFE_SCRIPT = r"""args => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  if (!root.classList.contains('splide--rtl')) return {ok: false, reason: 'rtl_class'};
  const visible = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < innerWidth && rect.top < innerHeight;
  };
  const contained = (node, owner) => {
    const rect = node.getBoundingClientRect(), box = owner.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && box.width > 0 && box.height > 0 &&
      rect.left >= box.left - 1 && rect.top >= box.top - 1 &&
      rect.right <= box.right + 1 && rect.bottom <= box.bottom + 1;
  };
  const prefix = (node, value) => [...node.classList].some(name => name.startsWith(value));
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (!visible(root) || active.length !== 1 || slides.indexOf(active[0]) !== 0 ||
      !visible(active[0]) || slides.length !== args.endIndex + 2)
    return {ok: false, reason: 'active_or_inventory'};
  const begins = [...root.querySelectorAll('div[data-type="beginning"]')];
  const prs = [...root.querySelectorAll('div[data-type="pr"]')];
  const beginPrs = begins.length === 1
    ? [...begins[0].querySelectorAll('div[data-type="pr"]')] : [];
  const begin = begins[0], beginPr = beginPrs[0];
  const finalPr = prs.find(node => !node.closest('div[data-type="beginning"]'));
  if (begins.length !== 1 || prs.length !== 2 || beginPrs.length !== 1 ||
      begin.closest('.splide__slide') !== active[0] || !prefix(begin, '_root_1w5tt_') ||
      begin.getAttribute('data-n') !== null || !contained(begin, active[0]) || !visible(begin) ||
      !beginPr || !prefix(beginPr, '_endOfBook_') || prefix(beginPr, '_endOfBookWrapper_') ||
      beginPr.getAttribute('data-n') !== null || beginPr.closest('.splide__slide') !== active[0] ||
      !contained(beginPr, active[0]) || !visible(beginPr) || !finalPr ||
      !prefix(finalPr, '_endOfBookWrapper_') || prefix(finalPr, '_endOfBook_') ||
      finalPr.getAttribute('data-n') !== '2' ||
      slides.indexOf(finalPr.closest('.splide__slide')) !== args.endIndex - 1 ||
      !contained(finalPr, finalPr.closest('.splide__slide')) ||
      active[0].querySelectorAll('div[data-type="contents"]').length !== 0 ||
      slides[1].querySelectorAll('div[data-type="contents"]').length !== 2)
    return {ok: false, reason: 'beginning_final_pr_roles'};
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')].filter(node => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden' &&
      getComputedStyle(node).display !== 'none';
  });
  if (dialogs.length) return {ok: false, reason: 'visible_dialog'};
  const focus = document.activeElement;
  if (focus !== document.body && focus !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: 0};
}""";

_BEGINNING_PR_FINAL_PR_FINAL_ARROW_SAFE_SCRIPT = r"""args => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0];
  if (!root.classList.contains('splide--rtl')) return {ok: false, reason: 'rtl_class'};
  const visible = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < innerWidth && rect.top < innerHeight;
  };
  const contained = (node, owner) => {
    const rect = node.getBoundingClientRect(), box = owner.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && box.width > 0 && box.height > 0 &&
      rect.left >= box.left - 1 && rect.top >= box.top - 1 &&
      rect.right <= box.right + 1 && rect.bottom <= box.bottom + 1;
  };
  const prefix = (node, value) => [...node.classList].some(name => name.startsWith(value));
  const slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  if (!visible(root) || active.length !== 1 || slides.indexOf(active[0]) !== args.activeIndex ||
      args.activeIndex !== args.endIndex - 1 || !visible(active[0]) ||
      slides.length !== args.endIndex + 2)
    return {ok: false, reason: 'active_or_inventory'};
  const begins = [...root.querySelectorAll('div[data-type="beginning"]')];
  const prs = [...root.querySelectorAll('div[data-type="pr"]')];
  const beginPrs = begins.length === 1
    ? [...begins[0].querySelectorAll('div[data-type="pr"]')] : [];
  const beginPr = beginPrs[0];
  const finalPrs = prs.filter(node => !node.closest('div[data-type="beginning"]'));
  const finalPr = finalPrs[0];
  const currentContents = [...active[0].querySelectorAll('div[data-type="contents"]')]
    .filter(node => prefix(node, '_pageCanvasWrapper_'));
  if (begins.length !== 1 || prs.length !== 2 || beginPrs.length !== 1 || !beginPr ||
      !prefix(beginPr, '_endOfBook_') || prefix(beginPr, '_endOfBookWrapper_') ||
      beginPr.getAttribute('data-n') !== null || begins[0].getAttribute('data-n') !== null ||
      begins[0].closest('.splide__slide') !== slides[0] ||
      finalPrs.length !== 1 || !finalPr || !prefix(finalPr, '_endOfBookWrapper_') ||
      prefix(finalPr, '_endOfBook_') || finalPr.getAttribute('data-n') !== '2' ||
      finalPr.closest('.splide__slide') !== active[0] || !contained(finalPr, active[0]) ||
      !visible(finalPr) || currentContents.length !== 1 || currentContents.length !== args.slotCount)
    return {ok: false, reason: 'final_pr_role'};
  const endSlide = slides[args.endIndex];
  const endMarkers = [...endSlide.querySelectorAll('div[data-type="end-of-book"][data-n]')]
    .filter(node => prefix(node, '_endOfBookWrapper_'));
  const endNumbers = endMarkers.map(node => node.getAttribute('data-n'));
  if (currentContents.length !== 1 ||
      endSlide.querySelectorAll('div[data-type="contents"]').length !== 0 ||
      endMarkers.length !== 2 || endNumbers[0] !== '1' || endNumbers[1] !== '2' ||
      endMarkers.some(node => !contained(node, endSlide)))
    return {ok: false, reason: 'next_paired_end'};
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')].filter(node => {
    const rect = node.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && getComputedStyle(node).visibility !== 'hidden' &&
      getComputedStyle(node).display !== 'none';
  });
  if (dialogs.length) return {ok: false, reason: 'visible_dialog'};
  const focus = document.activeElement;
  if (focus !== document.body && focus !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: args.activeIndex, slotCount: currentContents.length};
}""";


_DIRECT_FIRST_ARROW_SAFE_SCRIPT = r"""() => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  const roots = screens.length === 1 ? [...screens[0].querySelectorAll('.splide._root_1542n_1')] : [];
  if (roots.length !== 1) return {ok: false};
  const root = roots[0], slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(node => node.classList.contains('is-active'));
  const nodes = slides[0] ? [...slides[0].querySelectorAll('[data-type="contents"]')] : [];
  const beginnings = [...root.querySelectorAll('div[data-type="beginning"]')];
  const visible = node => { const r = node.getBoundingClientRect(), s = getComputedStyle(node);
    return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 &&
      r.left < innerWidth && r.top < innerHeight && s.display !== 'none' && s.visibility !== 'hidden'; };
  if (!root.classList.contains('splide--rtl') || !visible(root) || active.length !== 1 ||
      active[0] !== slides[0] || nodes.length !== 1 || nodes[0].tagName !== 'CANVAS' ||
      beginnings.length !== 1 || beginnings[0].closest('.splide__slide') !== slides[0] ||
      nodes[0].closest('div[data-type="beginning"]') !== beginnings[0] || !visible(beginnings[0]) ||
      ![...nodes[0].classList].some(name => name.startsWith('_root_bx4cr_')) || !visible(nodes[0]) ||
      [...document.querySelectorAll('[role="dialog"], dialog')].some(visible) ||
      (document.activeElement !== document.body && document.activeElement !== document.documentElement))
    return {ok: false};
  return {ok: true, activeIndex: 0, slotCount: 1};
}""";

_PAIRED_FIRST_PR_ARROW_SAFE_SCRIPT = r"""args => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0], slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  const prefix = (node, value) => [...node.classList].some(name => name.startsWith(value));
  const visible = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < innerWidth && rect.top < innerHeight;
  };
  const contained = (node, owner) => {
    const rect = node.getBoundingClientRect(), box = owner.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && box.width > 0 && box.height > 0 &&
      rect.left >= box.left - 1 && rect.top >= box.top - 1 &&
      rect.right <= box.right + 1 && rect.bottom <= box.bottom + 1;
  };
  if (!root.classList.contains('splide--rtl') || !visible(root) || args.endIndex < 2 ||
      slides.length !== args.endIndex + (args.bridge ? 1 : 2) || active.length !== 1 ||
      active[0] !== slides[args.endIndex - 1] || !visible(active[0]))
    return {ok: false, reason: 'active_or_inventory'};
  const prs = [...root.querySelectorAll('div[data-type="pr"]')];
  const beginnings = [...root.querySelectorAll('div[data-type="beginning"]')];
  if ((args.directFirst ? (beginnings.length !== 1 ||
      beginnings[0].closest('.splide__slide') !== slides[0] ||
      !prefix(beginnings[0], '_root_1w5tt_') || !contained(beginnings[0], slides[0]) ||
      beginnings[0].querySelectorAll('div[data-type="pr"]').length !== 0) : beginnings.length !== 0) || prs.length !== 1)
    return {ok: false, reason: 'pr_inventory'};
  const pr = prs[0];
  if (!prefix(pr, '_endOfBookWrapper_') || prefix(pr, '_endOfBook_') ||
      pr.getAttribute('data-n') !== (args.bridge ? '1' : '2') || pr.closest('.splide__slide') !== active[0] ||
      pr.closest('div[data-type="beginning"]') !== null || !contained(pr, active[0]) || !visible(pr))
    return {ok: false, reason: 'pr_role_or_geometry'};
  const contents = [...active[0].querySelectorAll('div[data-type="contents"]')];
  const canvases = contents.length === 1 ? [...contents[0].querySelectorAll('canvas')] : [];
  if (args.bridge ? contents.length !== 0 :
      (contents.length !== 1 || !prefix(contents[0], '_pageCanvasWrapper_') ||
       canvases.length !== 1 || !prefix(canvases[0], '_root_bx4cr_')))
    return {ok: false, reason: 'final_slot'};
  const ends = [...root.querySelectorAll('div[data-type="end-of-book"]')];
  if (ends.length !== (args.doubleEnd ? 4 : 3)) return {ok: false, reason: 'end_inventory'};
  const roles = args.bridge ? [[args.endIndex - 1, '2'], [args.endIndex, '1'], [args.endIndex, '2']] :
    (args.doubleEnd ? [[args.endIndex, '1'], [args.endIndex, '2'], [args.endIndex + 1, '1'], [args.endIndex + 1, '2']] :
      [[args.endIndex, '1'], [args.endIndex, '2']]);
  for (let i = 0; i < roles.length; i++) {
    const owner = slides[roles[i][0]], marker = ends[i];
    if ((!args.bridge && owner.classList.contains('is-active')) ||
        owner.querySelectorAll('div[data-type="contents"]').length !== 0 ||
        !prefix(marker, '_endOfBookWrapper_') || prefix(marker, '_endOfBook_') ||
        marker.getAttribute('data-n') !== roles[i][1] ||
        marker.closest('.splide__slide') !== owner || !contained(marker, owner))
      return {ok: false, reason: 'double_end'};
  }
  if (!args.bridge && !args.doubleEnd) {
    const marker = ends[2], owner = slides[args.endIndex + 1];
    if (!prefix(marker, '_endOfBook_') || prefix(marker, '_endOfBookWrapper_') ||
        marker.getAttribute('data-n') !== null || marker.closest('.splide__slide') !== owner ||
        owner.classList.contains('is-active') || owner.querySelectorAll('div[data-type="contents"]').length ||
        !contained(marker, owner)) return {ok: false, reason: 'recommendation'};
  }
  if ([...document.querySelectorAll('[role="dialog"], dialog')].some(visible))
    return {ok: false, reason: 'visible_dialog'};
  if (document.activeElement !== document.body && document.activeElement !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: args.endIndex - 1, slotCount: args.bridge ? 0 : 1};
}""";

_CONTENT_FIRST_FINAL_PR_ARROW_SAFE_SCRIPT = r"""args => {
  const screens = [...document.querySelectorAll('._mainScreen_191o7_1')];
  if (screens.length !== 1) return {ok: false, reason: 'main_screen_count'};
  const roots = [...screens[0].querySelectorAll('.splide._root_1542n_1')];
  if (roots.length !== 1) return {ok: false, reason: 'reader_root_count'};
  const root = roots[0], slides = [...root.querySelectorAll('.splide__slide')];
  const active = slides.filter(slide => slide.classList.contains('is-active'));
  const prefix = (node, value) => [...node.classList].some(name => name.startsWith(value));
  const visible = node => {
    const style = getComputedStyle(node), rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.bottom > 0 &&
      rect.left < innerWidth && rect.top < innerHeight;
  };
  const contained = (node, owner) => {
    const rect = node.getBoundingClientRect(), box = owner.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && box.width > 0 && box.height > 0 &&
      rect.left >= box.left - 1 && rect.top >= box.top - 1 &&
      rect.right <= box.right + 1 && rect.bottom <= box.bottom + 1;
  };
  if (!root.classList.contains('splide--rtl') || !visible(root) || slides.length !== args.endIndex + 2 ||
      args.endIndex < 3 || active.length !== 1 || active[0] !== slides[args.endIndex - 1] ||
      !visible(active[0])) return {ok: false, reason: 'active_or_inventory'};
  const beginnings = [...root.querySelectorAll('div[data-type="beginning"]')];
  const prs = [...root.querySelectorAll('div[data-type="pr"]')];
  const firstPRs = prs.filter(node => node.closest('.splide__slide') === slides[0]);
  const finalPRs = prs.filter(node => node.closest('.splide__slide') === slides[args.endIndex - 1]);
  const finalPR = finalPRs[0], firstPR = firstPRs[0];
  const finalContents = [...active[0].querySelectorAll('div[data-type="contents"]')]
    .filter(node => prefix(node, '_pageCanvasWrapper_'));
  const finalCanvases = finalContents.length === 1 ? [...finalContents[0].querySelectorAll('canvas')] : [];
  const endSlide = slides[args.endIndex];
  const mainEnd = [...endSlide.querySelectorAll('div[data-type="end-of-book"]')]
    .filter(node => prefix(node, '_endOfBookWrapper_'));
  const endNumbers = mainEnd.map(node => node.getAttribute('data-n'));
  const recommendationSlide = slides[args.endIndex + 1];
  const recommendations = [...root.querySelectorAll('div[data-type="end-of-book"]')]
    .filter(node => prefix(node, '_endOfBook_') && !prefix(node, '_endOfBookWrapper_'));
  if (beginnings.length !== 0 || prs.length !== 2 || firstPRs.length !== 1 || finalPRs.length !== 1)
    return {ok: false, reason: 'pr_inventory'};
  if (!prefix(firstPR, '_endOfBookWrapper_') || prefix(firstPR, '_endOfBook_') ||
      firstPR.getAttribute('data-n') !== '1' || firstPR.closest('div[data-type="beginning"]') !== null ||
      !contained(firstPR, slides[0]) ||
      !prefix(finalPR, '_endOfBookWrapper_') || prefix(finalPR, '_endOfBook_') ||
      finalPR.getAttribute('data-n') !== '2' || finalPR.closest('div[data-type="beginning"]') !== null ||
      !contained(finalPR, active[0]) || !visible(finalPR))
    return {ok: false, reason: 'pr_role_or_geometry'};
  if (finalContents.length !== 1 || finalCanvases.length !== 1 || !prefix(finalCanvases[0], '_root_bx4cr_'))
    return {ok: false, reason: 'final_slot'};
  if (endSlide.querySelectorAll('div[data-type="contents"]').length !== 0 || mainEnd.length !== 2 ||
      endNumbers[0] !== '1' || endNumbers[1] !== '2' || mainEnd.some(node => !contained(node, endSlide)))
    return {ok: false, reason: 'paired_end'};
  if (recommendationSlide.classList.contains('is-active') ||
      recommendationSlide.querySelectorAll('div[data-type="contents"]').length !== 0 ||
      recommendations.length !== 1 || recommendations[0].closest('.splide__slide') !== recommendationSlide ||
      recommendations[0].getAttribute('data-n') !== null || !contained(recommendations[0], recommendationSlide))
    return {ok: false, reason: 'recommendation'};
  const dialogs = [...document.querySelectorAll('[role="dialog"], dialog')].filter(visible);
  if (dialogs.length) return {ok: false, reason: 'visible_dialog'};
  const focus = document.activeElement;
  if (focus !== document.body && focus !== document.documentElement)
    return {ok: false, reason: 'unexpected_focus'};
  return {ok: true, activeIndex: args.endIndex - 1, endIndex: args.endIndex, slotCount: 1,
    firstPR: {dataN: firstPR.getAttribute('data-n'), slideIndex: 0},
    finalPR: {dataN: finalPR.getAttribute('data-n'), slideIndex: args.endIndex - 1},
    endNumbers, recommendationIndex: args.endIndex + 1};
}""";


def _snapshot_signature(
    snapshot: dict[str, Any], *, include_pr_markers: bool = False
) -> tuple[object, ...]:
    rows = snapshot.get("slideRows")
    if not isinstance(rows, list):
        return ()
    signature: list[object] = [
        snapshot.get("rootId"), snapshot.get("activeIndex"),
        snapshot.get("directFirstContent"), snapshot.get("directFirstBeginningOwnerIndex"),
    ]
    for row in rows:
        if not isinstance(row, dict):
            return ()
        canvases = row.get("contentCanvases")
        if not isinstance(canvases, list):
            return ()
        signature.append(
            (
                row.get("id"),
                row.get("index"),
                row.get("contentSlots"),
                tuple(
                    (
                        canvas.get("slot"),
                        canvas.get("width"),
                        canvas.get("height"),
                        tuple(sorted((canvas.get("box") or {}).items())),
                        canvas.get("drawCount"),
                        canvas.get("mutationCount"),
                        tuple(sorted((canvas.get("last") or {}).items()))
                        if isinstance(canvas.get("last"), dict)
                        else None,
                    )
                    for canvas in canvases
                    if isinstance(canvas, dict)
                ),
            )
        )
    for marker_key in (
        "mainEndMarkers",
        "secondaryEndMarkers",
        "beginningMarkers",
        "prMarkers",
    ):
        markers = snapshot.get(marker_key)
        if (
            marker_key == "prMarkers"
            and snapshot.get("beginningMarkerCount") == 0
            and not include_pr_markers
        ):
            markers = []
        if not isinstance(markers, list):
            signature.append((marker_key, None))
            continue
        signature.append(
            (
                marker_key,
                tuple(
                    (
                        marker.get("tagName"),
                        marker.get("wrapperClass"),
                        marker.get("secondaryClass"),
                        marker.get("dataType"),
                        marker.get("dataN"),
                        marker.get("slideIndex"),
                        marker.get("rootClass"),
                        marker.get("beginningOwnerIndex"),
                        marker.get("prMarkerCount"),
                        tuple(sorted((marker.get("box") or {}).items()))
                        if isinstance(marker.get("box"), dict)
                        else None,
                    )
                    for marker in markers
                    if isinstance(marker, dict)
                ),
            )
        )
    return tuple(signature)


def _pr_marker_signature(snapshot: dict[str, Any]) -> tuple[object, ...]:
    markers = snapshot.get("prMarkers")
    if not isinstance(markers, list):
        return ()
    return tuple(
        (
            marker.get("tagName"),
            marker.get("wrapperClass"),
            marker.get("secondaryClass"),
            marker.get("dataType"),
            marker.get("dataN"),
            marker.get("slideIndex"),
            marker.get("beginningOwnerIndex"),
            tuple(sorted((marker.get("box") or {}).items()))
            if isinstance(marker.get("box"), dict)
            else None,
        )
        for marker in markers
        if isinstance(marker, dict)
    )


class KadocomiAdapter(SiteAdapter):
    """Capture one exact, currently public Kadocomi WEB episode."""

    def __init__(self) -> None:
        self._source_url: str | None = None
        self._target_url: str | None = None
        self._work_id: str | None = None
        self._episode_id: str | None = None
        self._external_id: str | None = None
        self._opaque_work_key: str | None = None
        self._work_title: str | None = None
        self._order_label: str | None = None
        self._all_slots: tuple[str, ...] = ()
        self._slide_slots: tuple[tuple[str, ...], ...] = ()
        self._end_slide_index: int | None = None
        self._reader_layout: str | None = None
        self._captured_slots: list[str] = []
        self._last_capture_slots: tuple[str, ...] = ()
        self._pending_next_index: int | None = None
        self._ended = False
        self._capture_diagnostics: dict[str, object] = {"mode": "not_started"}
        self._main_document_responses: list[tuple[str, int]] = []
        self._response_listener: Any | None = None

    async def prepare_page(self, page: Page) -> None:
        try:
            await page.add_init_script(NATIVE_OBSERVER_INIT_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi native image observer could not be installed") from exc

        self._main_document_responses = []

        def observe_response(response: Response) -> None:
            request = response.request
            try:
                if (
                    request.is_navigation_request()
                    and request.resource_type == "document"
                    and request.frame == page.main_frame
                ):
                    self._main_document_responses.append((response.url, response.status))
            except PlaywrightError:
                return

        self._response_listener = observe_response
        page.on("response", observe_response)

    def resolve_initial_navigation_url(self, source_url: str) -> str:
        identity = parse_kadocomi_episode_url(source_url)
        if identity is None:
            raise UnknownPageStateError("Kadocomi requires an exact absolute episode URL")
        external = f"{identity.work_id}:{identity.episode_id}"
        if self._external_id is not None and self._external_id != external:
            raise UnknownPageStateError("Kadocomi URL differs from the configured Catalog source")
        canonical_url = canonical_kadocomi_episode_url(source_url)
        if self._opaque_work_key is not None and source_url != canonical_url:
            raise UnknownPageStateError(
                "Kadocomi Batch target must be a canonical query-free episode URL"
            )
        self._source_url = canonical_url
        self._target_url = self._source_url
        self._work_id = identity.work_id
        self._episode_id = identity.episode_id
        self._external_id = external
        return self._target_url

    def get_access_profile(self) -> AccessProfile:
        return kadocomi_access_profile()

    async def configure_run(self, page: Page, access_strategy: AccessStrategy) -> None:
        del page
        if access_strategy != "direct":
            raise UnsupportedAccessStrategyError(
                "Kadocomi supports only the verified direct free WEB path"
            )

    async def configure_quota_resource(self, page: Page, quota_resource: str | None) -> None:
        del page
        if quota_resource is not None:
            raise UnsupportedAccessStrategyError("Kadocomi does not support access resources")

    async def configure_target_identity(self, external_id: str, work_key: str) -> None:
        match = _EXTERNAL_ID.fullmatch(external_id)
        if match is None or not isinstance(work_key, str) or not work_key.strip():
            raise UnknownPageStateError("Kadocomi Catalog target identity is malformed")
        if self._external_id is not None and self._external_id != external_id:
            raise UnknownPageStateError("Kadocomi Catalog identity was configured inconsistently")
        self._external_id = external_id
        self._work_id = match.group("work")
        self._episode_id = match.group("episode")
        self._opaque_work_key = work_key

    async def initialize_entry_only(self, page: Page) -> None:
        del page
        raise UnsupportedAccessStrategyError("Kadocomi does not support entry-only access")

    def get_initialize_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, INITIALIZE_TIMEOUT_MS)

    def get_page_change_timeout_ms(self, default_ms: int) -> int:
        return max(default_ms, int(PAGE_CHANGE_TIMEOUT_SECONDS * 1000))

    async def initialize(self, page: Page) -> None:
        if self._target_url is None or self._work_id is None or self._episode_id is None:
            raise UnknownPageStateError("Kadocomi exact episode target was not configured")
        if parse_kadocomi_episode_url(self._source_url or "") is None:
            raise UnknownPageStateError("Kadocomi canonical source URL is invalid")
        self._captured_slots = []
        self._last_capture_slots = ()
        self._pending_next_index = None
        self._ended = False
        self._all_slots = ()
        self._slide_slots = ()
        self._end_slide_index = None
        self._reader_layout = None
        try:
            await self._validate_initial_navigation_response(page)
            self._validate_current_episode_url(page)
            await self._wait_for_episode_metadata(page)
            await self._wait_for_initial_reader(page)
            if self._reader_layout in {
                _BEGINNING_PR_PAIRED_LAYOUT,
                _BEGINNING_PR_MIXED_FINAL_LAYOUT,
                _BEGINNING_PR_FINAL_PR_LAYOUT,
            }:
                await self._advance_beginning_pr_entry(page)
        finally:
            self._remove_response_listener(page)

    def _remove_response_listener(self, page: Page) -> None:
        if self._response_listener is not None:
            page.remove_listener("response", self._response_listener)
            self._response_listener = None

    async def _validate_initial_navigation_response(self, page: Page) -> None:
        responses = self._main_document_responses
        self._main_document_responses = []
        if not responses:
            raise UnknownPageStateError("Kadocomi exact episode navigation had no document response")
        for response_url, status in responses:
            identity = parse_kadocomi_episode_url(response_url)
            if (
                identity is None
                or identity.work_id != self._work_id
                or identity.episode_id != self._episode_id
                or status < 200
                or status >= 400
            ):
                raise UnknownPageStateError("Kadocomi exact episode navigation was unavailable or redirected")
        final_url, final_status = responses[-1]
        final_identity = parse_kadocomi_episode_url(final_url)
        page_identity = parse_kadocomi_episode_url(page.url)
        if (
            final_status != 200
            or final_identity is None
            or page_identity is None
            or final_identity.work_id != page_identity.work_id
            or final_identity.episode_id != page_identity.episode_id
        ):
            raise UnknownPageStateError("Kadocomi exact episode route did not return HTTP 200")

    def _validate_current_episode_url(self, page: Page) -> None:
        identity = parse_kadocomi_episode_url(page.url)
        if (
            identity is None
            or identity.work_id != self._work_id
            or identity.episode_id != self._episode_id
        ):
            raise UnknownPageStateError("Kadocomi navigation changed the exact work or episode")

    async def _read_episode_metadata(self, page: Page) -> dict[str, Any] | None:
        self._validate_current_episode_url(page)
        try:
            raw = await asyncio.wait_for(page.evaluate(_READ_EPISODE_METADATA_SCRIPT), timeout=4)
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Kadocomi episode metadata could not be read") from exc
        return raw if isinstance(raw, dict) else None

    async def _wait_for_episode_metadata(self, page: Page) -> None:
        deadline = asyncio.get_running_loop().time() + METADATA_READY_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            raw = await self._read_episode_metadata(page)
            if raw is None:
                await page.wait_for_timeout(VIEWER_POLL_MS)
                continue
            if raw.get("visibleDialogCount") != 0:
                raise UnknownPageStateError("Kadocomi episode opened a visible access dialog")
            heading = raw.get("heading")
            match = _EPISODE_HEADING.fullmatch(heading) if isinstance(heading, str) else None
            title = f"{heading}{_OG_TITLE_SUFFIX}" if isinstance(heading, str) else None
            if (
                match is not None
                and raw.get("headingCount") == 1
                and raw.get("titleCount") == 1
                and raw.get("ogTitle") == title
                and raw.get("documentTitle") == title
                and match.group("order").strip()
                and match.group("work").strip()
            ):
                self._order_label = match.group("order").strip()
                self._work_title = match.group("work").strip()
                return
            await page.wait_for_timeout(VIEWER_POLL_MS)
        raise UnknownPageStateError("Kadocomi exact episode metadata did not settle consistently")

    async def _validate_episode_metadata(self, page: Page) -> None:
        raw = await self._read_episode_metadata(page)
        expected_heading = (
            f"\u3010{self._order_label}\u3011{self._work_title}"
            if self._order_label is not None and self._work_title is not None
            else None
        )
        expected_title = f"{expected_heading}{_OG_TITLE_SUFFIX}" if expected_heading else None
        if (
            raw is None
            or raw.get("headingCount") != 1
            or raw.get("heading") != expected_heading
            or raw.get("titleCount") != 1
            or raw.get("ogTitle") != expected_title
            or raw.get("documentTitle") != expected_title
            or raw.get("visibleDialogCount") != 0
        ):
            raise UnknownPageStateError("Kadocomi episode identity or access surface is unknown")

    async def _snapshot(self, page: Page, *, include_nodes: bool = False) -> dict[str, Any]:
        try:
            value = await asyncio.wait_for(
                page.evaluate(
                    "includeNodes => window.__kadocomiNativeCaptureV1?.snapshot(includeNodes) ?? null",
                    include_nodes,
                ),
                timeout=3,
            )
        except (PlaywrightError, TimeoutError) as exc:
            raise UnknownPageStateError("Kadocomi viewer snapshot failed") from exc
        if not isinstance(value, dict):
            raise UnknownPageStateError("Kadocomi viewer observer is unavailable")
        return value

    @staticmethod
    def _validate_main_end_markers(
        snapshot: dict[str, Any], expected: list[tuple[str, int]]
    ) -> None:
        indexes = snapshot.get("markerSlideIndexes")
        numbers = snapshot.get("markerNumbers")
        records = snapshot.get("mainEndMarkers")
        if (
            not isinstance(indexes, list)
            or indexes != [slide_index for _number, slide_index in expected]
            or numbers != [number for number, _slide_index in expected]
            or not isinstance(records, list)
            or len(records) != len(expected)
        ):
            raise UnknownPageStateError("Kadocomi main END marker order or ownership changed")
        for record, (number, slide_index) in zip(records, expected, strict=True):
            if (
                not isinstance(record, dict)
                or record.get("tagName") != "DIV"
                or record.get("wrapperClass") is not True
                or record.get("secondaryClass") is not False
                or record.get("dataType") != "end-of-book"
                or record.get("dataN") != number
                or record.get("slideIndex") != slide_index
            ):
                raise UnknownPageStateError("Kadocomi main END marker class or slide owner changed")
            box = record.get("box")
            fields = ("x", "y", "width", "height", "slideWidth", "slideHeight")
            if (
                not isinstance(box, dict)
                or any(
                    isinstance(box.get(field), bool)
                    or not isinstance(box.get(field), (int, float))
                    or not math.isfinite(box[field])
                    for field in fields
                )
                or box["width"] <= 0
                or box["height"] <= 0
                or box["slideWidth"] <= 0
                or box["slideHeight"] <= 0
                or box["x"] < -1
                or box["y"] < -1
                or box["x"] + box["width"] > box["slideWidth"] + 1
                or box["y"] + box["height"] > box["slideHeight"] + 1
            ):
                raise UnknownPageStateError("Kadocomi main END marker geometry is invalid")

    @staticmethod
    def _validate_secondary_end_markers(
        snapshot: dict[str, Any], expected_indexes: list[int]
    ) -> None:
        indexes = snapshot.get("secondaryEndMarkerSlideIndexes")
        records = snapshot.get("secondaryEndMarkers")
        if (
            not isinstance(indexes, list)
            or indexes != expected_indexes
            or not isinstance(records, list)
            or len(records) != len(expected_indexes)
        ):
            raise UnknownPageStateError("Kadocomi recommendation END marker ownership changed")
        for record, slide_index in zip(records, expected_indexes, strict=True):
            if (
                not isinstance(record, dict)
                or record.get("tagName") != "DIV"
                or record.get("wrapperClass") is not False
                or record.get("secondaryClass") is not True
                or record.get("dataType") != "end-of-book"
                or record.get("slideIndex") != slide_index
            ):
                raise UnknownPageStateError("Kadocomi recommendation END marker class changed")

    @staticmethod
    def _marker_geometry_is_valid(box: object) -> bool:
        fields = ("x", "y", "width", "height", "slideWidth", "slideHeight")
        if not isinstance(box, dict) or any(
            isinstance(box.get(field), bool)
            or not isinstance(box.get(field), (int, float))
            or not math.isfinite(box[field])
            for field in fields
        ):
            return False
        return (
            box["width"] > 0
            and box["height"] > 0
            and box["slideWidth"] > 0
            and box["slideHeight"] > 0
            and box["x"] >= -1
            and box["y"] >= -1
            and box["x"] + box["width"] <= box["slideWidth"] + 1
            and box["y"] + box["height"] <= box["slideHeight"] + 1
        )

    @classmethod
    def _validate_beginning_pr_markers(
        cls, snapshot: dict[str, Any]
    ) -> None:
        beginning_markers = snapshot.get("beginningMarkers")
        pr_markers = snapshot.get("prMarkers")
        if (
            snapshot.get("beginningMarkerCount") != 1
            or not isinstance(beginning_markers, list)
            or len(beginning_markers) != 1
            or snapshot.get("prMarkerCount") != 1
            or not isinstance(pr_markers, list)
            or len(pr_markers) != 1
        ):
            raise UnknownPageStateError("Kadocomi initial empty slide has no unique beginning PR marker")
        beginning = beginning_markers[0]
        pr = pr_markers[0]
        if (
            not isinstance(beginning, dict)
            or beginning.get("tagName") != "DIV"
            or beginning.get("rootClass") is not True
            or beginning.get("dataType") != "beginning"
            or beginning.get("dataN") is not None
            or beginning.get("slideIndex") != 0
            or beginning.get("prMarkerCount") != 1
            or not cls._marker_geometry_is_valid(beginning.get("box"))
            or not isinstance(pr, dict)
            or pr.get("tagName") != "DIV"
            or pr.get("wrapperClass") is not False
            or pr.get("secondaryClass") is not True
            or pr.get("dataType") != "pr"
            or pr.get("dataN") is not None
            or pr.get("slideIndex") != 0
            or pr.get("beginningOwnerIndex") != 0
            or not cls._marker_geometry_is_valid(pr.get("box"))
        ):
            raise UnknownPageStateError("Kadocomi initial beginning PR marker ownership or geometry is unknown")

    @classmethod
    def _validate_beginning_final_pr_markers(
        cls, snapshot: dict[str, Any], end_index: int
    ) -> None:
        beginning_markers = snapshot.get("beginningMarkers")
        pr_markers = snapshot.get("prMarkers")
        if (
            snapshot.get("beginningMarkerCount") != 1
            or not isinstance(beginning_markers, list)
            or len(beginning_markers) != 1
            or snapshot.get("prMarkerCount") != 2
            or not isinstance(pr_markers, list)
            or len(pr_markers) != 2
        ):
            raise UnknownPageStateError("Kadocomi beginning/final PR roles are missing or duplicated")
        beginning = beginning_markers[0]
        beginning_prs = [
            marker for marker in pr_markers
            if isinstance(marker, dict) and marker.get("beginningOwnerIndex") == 0
        ]
        final_prs = [
            marker for marker in pr_markers
            if isinstance(marker, dict) and marker.get("beginningOwnerIndex") == -1
        ]
        if (
            not isinstance(beginning, dict)
            or beginning.get("tagName") != "DIV"
            or beginning.get("rootClass") is not True
            or beginning.get("dataType") != "beginning"
            or beginning.get("dataN") is not None
            or beginning.get("slideIndex") != 0
            or beginning.get("prMarkerCount") != 1
            or not cls._marker_geometry_is_valid(beginning.get("box"))
            or len(beginning_prs) != 1
            or len(final_prs) != 1
        ):
            raise UnknownPageStateError("Kadocomi beginning/final PR ownership is ambiguous")
        beginning_pr = beginning_prs[0]
        final_pr = final_prs[0]
        if (
            beginning_pr.get("tagName") != "DIV"
            or beginning_pr.get("wrapperClass") is not False
            or beginning_pr.get("secondaryClass") is not True
            or beginning_pr.get("dataType") != "pr"
            or beginning_pr.get("dataN") is not None
            or beginning_pr.get("slideIndex") != 0
            or not cls._marker_geometry_is_valid(beginning_pr.get("box"))
            or final_pr.get("tagName") != "DIV"
            or final_pr.get("wrapperClass") is not True
            or final_pr.get("secondaryClass") is not False
            or final_pr.get("dataType") != "pr"
            or final_pr.get("dataN") != "2"
            or final_pr.get("slideIndex") != end_index - 1
            or not cls._marker_geometry_is_valid(final_pr.get("box"))
        ):
            raise UnknownPageStateError("Kadocomi beginning/final PR class, number, or geometry is unknown")

    @classmethod
    def _validate_content_first_final_pr_markers(
        cls, snapshot: dict[str, Any], end_index: int
    ) -> None:
        beginning_markers = snapshot.get("beginningMarkers")
        pr_markers = snapshot.get("prMarkers")
        if (
            end_index < 3
            or snapshot.get("beginningMarkerCount") != 0
            or beginning_markers != []
            or snapshot.get("prMarkerCount") != 2
            or not isinstance(pr_markers, list)
            or len(pr_markers) != 2
        ):
            raise UnknownPageStateError("Kadocomi content-first final PR roles are missing or duplicated")
        expected = [("1", 0), ("2", end_index - 1)]
        for marker, (number, slide_index) in zip(pr_markers, expected, strict=True):
            if (
                not isinstance(marker, dict)
                or marker.get("tagName") != "DIV"
                or marker.get("wrapperClass") is not True
                or marker.get("secondaryClass") is not False
                or marker.get("dataType") != "pr"
                or marker.get("dataN") != number
                or marker.get("slideIndex") != slide_index
                or marker.get("beginningOwnerIndex") != -1
                or not cls._marker_geometry_is_valid(marker.get("box"))
            ):
                raise UnknownPageStateError(
                    "Kadocomi content-first PR marker role, number, ownership, or geometry is unknown"
                )

    def _validate_inventory(
        self, snapshot: dict[str, Any]
    ) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...], int, str]:
        if (
            snapshot.get("status") != "ok"
            or snapshot.get("contentOutsideSlides") != 0
            or snapshot.get("hooksInstalled") is not True
            or snapshot.get("direction") not in {"ltr", "rtl"}
            or snapshot.get("rtlClass") is not True
        ):
            raise UnknownPageStateError("Kadocomi reader structure or native observer is unknown")
        rows = snapshot.get("slideRows")
        if not isinstance(rows, list) or len(rows) < 2 or len(rows) > MAX_CANVAS_SLOTS:
            raise UnknownPageStateError("Kadocomi reader slide list is incomplete or too large")
        marker_count = snapshot.get("endMarkerCount")
        marker_indexes = snapshot.get("markerSlideIndexes")
        marker_numbers = snapshot.get("markerNumbers")
        beginning_markers = snapshot.get("beginningMarkers")
        pr_markers = snapshot.get("prMarkers")
        if (
            isinstance(marker_count, bool)
            or not isinstance(marker_count, int)
            or not isinstance(marker_indexes, list)
            or len(marker_indexes) != marker_count
            or any(isinstance(index, bool) or not isinstance(index, int) for index in marker_indexes)
            or snapshot.get("unclassifiedEndMarkerCount") != 0
            or isinstance(snapshot.get("beginningMarkerCount"), bool)
            or not isinstance(snapshot.get("beginningMarkerCount"), int)
            or not isinstance(beginning_markers, list)
            or len(beginning_markers) != snapshot.get("beginningMarkerCount")
            or isinstance(snapshot.get("prMarkerCount"), bool)
            or not isinstance(snapshot.get("prMarkerCount"), int)
            or not isinstance(pr_markers, list)
            or len(pr_markers) != snapshot.get("prMarkerCount")
        ):
            raise UnknownPageStateError("Kadocomi explicit end marker is missing or malformed")
        if (
            marker_count == 2
            and len(set(marker_indexes)) == 1
            and marker_numbers == ["1", "2"]
        ):
            end_index = marker_indexes[0]
            trailing_count = len(rows) - end_index - 1
            if end_index < 1 or trailing_count not in (0, 1):
                raise UnknownPageStateError("Kadocomi paired END boundary or trailing slide is unknown")
            first_row = rows[0]
            first_slots = first_row.get("contentSlots") if isinstance(first_row, dict) else None
            if not isinstance(first_slots, list):
                raise UnknownPageStateError("Kadocomi initial slide inventory is malformed")
            if not first_slots:
                if snapshot.get("prMarkerCount") == 2:
                    if end_index < 3 or trailing_count != 1:
                        raise UnknownPageStateError("Kadocomi beginning/final PR boundary is unsupported")
                    # The final data-type=pr n=2 marker is not a main END marker.
                    self._validate_beginning_final_pr_markers(snapshot, end_index)
                    layout = _BEGINNING_PR_FINAL_PR_LAYOUT
                else:
                    if end_index < 2:
                        raise UnknownPageStateError("Kadocomi beginning PR has no following content slide")
                    self._validate_beginning_pr_markers(snapshot)
                    layout = _BEGINNING_PR_PAIRED_LAYOUT
            else:
                final_row = rows[end_index - 1]
                final_slots = final_row.get("contentSlots") if isinstance(final_row, dict) else None
                content_first_final_pr = (
                    end_index >= 3
                    and trailing_count == 1
                    and len(rows) == end_index + 2
                    and len(first_slots) == 1
                    and isinstance(final_slots, list)
                    and len(final_slots) == 1
                    and snapshot.get("prMarkerCount") == 2
                )
                if content_first_final_pr:
                    # These PR wrappers flank content; the following paired END alone ends the episode.
                    self._validate_content_first_final_pr_markers(snapshot, end_index)
                    layout = _CONTENT_FIRST_FINAL_PR_LAYOUT
                elif (
                    end_index >= 2 and trailing_count == 1 and len(first_slots) == 2
                    and isinstance(final_slots, list) and len(final_slots) == 1
                    and len(pr_markers) == 1
                ):
                    layout = _PAIRED_FIRST_FINAL_PR_LAYOUT
                elif (
                    snapshot.get("directFirstContent") is True and end_index >= 3
                    and trailing_count == 1 and len(first_slots) == 1
                    and isinstance(final_slots, list) and len(final_slots) == 1
                    and len(pr_markers) == 1
                ):
                    layout = _DIRECT_FIRST_FINAL_PR_LAYOUT
                else:
                    layout = _PAIRED_END_LAYOUT
            expected_main_markers = [("1", end_index), ("2", end_index)]
            expected_secondary_indexes = [end_index + 1] if trailing_count == 1 else []
        elif (
            marker_count == 3
            and marker_numbers == ["2", "1", "2"]
            and len(rows) >= 4
            and marker_indexes[0] + 1 == marker_indexes[1] == marker_indexes[2]
            and marker_indexes[1] >= 2
            and len(rows) - marker_indexes[1] - 1 in (0, 1)
            and snapshot.get("secondaryEndMarkerSlideIndexes")
            == ([marker_indexes[1] + 1] if len(rows) - marker_indexes[1] - 1 == 1 else [])
        ):
            layout = _MIXED_FINAL_END_LAYOUT
            end_index = marker_indexes[1]
            expected_main_markers = [
                ("2", end_index - 1),
                ("1", end_index),
                ("2", end_index),
            ]
            expected_secondary_indexes = [end_index + 1] if len(rows) - end_index - 1 else []
            first_row = rows[0]
            first_slots = first_row.get("contentSlots") if isinstance(first_row, dict) else None
            if not isinstance(first_slots, list):
                raise UnknownPageStateError("Kadocomi initial slide inventory is malformed")
            if not first_slots:
                if end_index < 3 or len(rows) - end_index - 1 != 0:
                    raise UnknownPageStateError("Kadocomi beginning/mixed-final boundary is unsupported")
                self._validate_beginning_pr_markers(snapshot)
                layout = _BEGINNING_PR_MIXED_FINAL_LAYOUT
            elif len(first_slots) == 2 and not rows[end_index - 1].get("contentSlots"):
                if len(rows) != end_index + 1:
                    raise UnknownPageStateError("Kadocomi paired-first PR/END has extra trailing slides")
                layout = _PAIRED_FIRST_PR_END_LAYOUT
            elif (
                snapshot.get("directFirstContent") is True and len(first_slots) == 1
                and end_index >= 3 and not rows[end_index - 1].get("contentSlots")
                and len(rows) == end_index + 1
            ):
                layout = _DIRECT_FIRST_PR_END_LAYOUT
        elif (
            marker_count == 4
            and marker_numbers == ["1", "2", "1", "2"]
            and marker_indexes[0] == marker_indexes[1] >= 2
            and marker_indexes[2] == marker_indexes[3] == marker_indexes[0] + 1
            and len(rows) == marker_indexes[0] + 2
        ):
            end_index = marker_indexes[0]
            layout = _PAIRED_FIRST_DOUBLE_END_LAYOUT
            expected_main_markers = [
                ("1", end_index), ("2", end_index),
                ("1", end_index + 1), ("2", end_index + 1),
            ]
            expected_secondary_indexes = []
            if (
                beginning_markers
                or len(pr_markers) != 1
                or not isinstance(pr_markers[0], dict)
                or pr_markers[0].get("tagName") != "DIV"
                or pr_markers[0].get("wrapperClass") is not True
                or pr_markers[0].get("secondaryClass") is not False
                or pr_markers[0].get("dataType") != "pr"
                or pr_markers[0].get("dataN") != "2"
                or pr_markers[0].get("slideIndex") != end_index - 1
                or pr_markers[0].get("beginningOwnerIndex") != -1
                or not self._marker_geometry_is_valid(pr_markers[0].get("box"))
            ):
                raise UnknownPageStateError("Kadocomi paired-first final PR role or geometry is unknown")
        else:
            raise UnknownPageStateError("Kadocomi END marker topology is unsupported or ambiguous")
        if snapshot.get("directFirstContent") is True and layout not in _DIRECT_FIRST_LAYOUTS:
            raise UnknownPageStateError("Kadocomi direct first canvas has an unsupported topology")
        if layout in {_PAIRED_FIRST_FINAL_PR_LAYOUT, *_PR_END_LAYOUTS, *_DIRECT_FIRST_LAYOUTS}:
            expected_number = "1" if layout in _PR_END_LAYOUTS else "2"
            if (
                (beginning_markers and layout not in _DIRECT_FIRST_LAYOUTS) or len(pr_markers) != 1
                or not isinstance(pr_markers[0], dict)
                or pr_markers[0].get("tagName") != "DIV"
                or pr_markers[0].get("wrapperClass") is not True
                or pr_markers[0].get("secondaryClass") is not False
                or pr_markers[0].get("dataType") != "pr"
                or pr_markers[0].get("dataN") != expected_number
                or pr_markers[0].get("slideIndex") != end_index - 1
                or pr_markers[0].get("beginningOwnerIndex") != -1
                or not self._marker_geometry_is_valid(pr_markers[0].get("box"))
            ):
                raise UnknownPageStateError("Kadocomi paired-first PR role or geometry is unknown")
        if layout in _DIRECT_FIRST_LAYOUTS and (
            len(beginning_markers) != 1 or not isinstance(beginning_markers[0], dict)
            or beginning_markers[0].get("tagName") != "DIV"
            or beginning_markers[0].get("rootClass") is not True
            or beginning_markers[0].get("dataType") != "beginning"
            or beginning_markers[0].get("dataN") is not None
            or beginning_markers[0].get("slideIndex") != 0
            or beginning_markers[0].get("prMarkerCount") != 0
            or snapshot.get("directFirstBeginningOwnerIndex") != 0
            or not self._marker_geometry_is_valid(beginning_markers[0].get("box"))
        ):
            raise UnknownPageStateError("Kadocomi direct first canvas beginning ownership is unknown")
        if snapshot.get("endMarkerCount") != len(expected_main_markers):
            raise UnknownPageStateError("Kadocomi main END marker count is inconsistent")
        self._validate_main_end_markers(snapshot, expected_main_markers)
        self._validate_secondary_end_markers(snapshot, expected_secondary_indexes)
        if layout in {_BEGINNING_PR_FINAL_PR_LAYOUT, _CONTENT_FIRST_FINAL_PR_LAYOUT, _PAIRED_FIRST_FINAL_PR_LAYOUT, _DIRECT_FIRST_FINAL_PR_LAYOUT}:
            secondary = snapshot.get("secondaryEndMarkers")
            if (
                not isinstance(secondary, list)
                or len(secondary) != 1
                or not isinstance(secondary[0], dict)
                or secondary[0].get("dataN") is not None
                or not self._marker_geometry_is_valid(secondary[0].get("box"))
            ):
                raise UnknownPageStateError("Kadocomi final recommendation geometry is invalid")
        slide_slots: list[tuple[str, ...]] = []
        flattened: list[str] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or row.get("index") != index:
                raise UnknownPageStateError("Kadocomi slide order is malformed")
            slots = row.get("contentSlots")
            canvases = row.get("contentCanvases")
            if (
                not isinstance(slots, list)
                or not all(isinstance(slot, str) and slot for slot in slots)
                or not isinstance(canvases, list)
                or len(canvases) != len(slots)
            ):
                raise UnknownPageStateError("Kadocomi content slot identity is incomplete")
            if layout == _PAIRED_END_LAYOUT:
                if index < end_index and (len(slots) > 2 or (index == 0 and len(slots) != 1)):
                    raise UnknownPageStateError("Kadocomi reader spread shape is unsupported")
                if 0 < index < end_index and len(slots) != 2:
                    raise UnknownPageStateError("Kadocomi observed right-to-left spread shape changed")
                if index >= end_index and slots:
                    raise UnknownPageStateError("Kadocomi found content at or after its explicit END")
            elif layout == _BEGINNING_PR_PAIRED_LAYOUT:
                if (index == 0 and slots) or (0 < index < end_index and len(slots) != 2):
                    raise UnknownPageStateError("Kadocomi beginning PR or paired content shape changed")
                if index >= end_index and slots:
                    raise UnknownPageStateError("Kadocomi found content at or after its explicit END")
            elif layout == _BEGINNING_PR_MIXED_FINAL_LAYOUT:
                if (
                    (index == 0 and slots)
                    or (0 < index < end_index - 1 and len(slots) != 2)
                    or (index == end_index - 1 and len(slots) != 1)
                    or (index >= end_index and slots)
                ):
                    raise UnknownPageStateError("Kadocomi beginning PR or mixed-final content shape changed")
            elif layout == _BEGINNING_PR_FINAL_PR_LAYOUT:
                if (
                    (index == 0 and slots)
                    or (0 < index < end_index - 1 and len(slots) != 2)
                    or (index == end_index - 1 and len(slots) != 1)
                    or (index >= end_index and slots)
                ):
                    raise UnknownPageStateError("Kadocomi beginning/final PR content shape changed")
            elif layout in _PR_END_LAYOUTS:
                if (
                    (index < end_index - 1 and len(slots) != (
                        1 if index == 0 and layout == _DIRECT_FIRST_PR_END_LAYOUT else 2
                    ))
                    or (index >= end_index - 1 and slots)
                ):
                    raise UnknownPageStateError("Kadocomi paired-first PR/END spread shape changed")
            elif layout in {_PAIRED_FIRST_DOUBLE_END_LAYOUT, _PAIRED_FIRST_FINAL_PR_LAYOUT}:
                if (
                    (index < end_index - 1 and len(slots) != 2)
                    or (index == end_index - 1 and len(slots) != 1)
                    or (index >= end_index and slots)
                ):
                    raise UnknownPageStateError("Kadocomi paired-first double-END spread shape changed")
            elif layout in {_CONTENT_FIRST_FINAL_PR_LAYOUT, _DIRECT_FIRST_FINAL_PR_LAYOUT}:
                if (
                    (index == 0 and len(slots) != 1)
                    or (0 < index < end_index - 1 and len(slots) != 2)
                    or (index == end_index - 1 and len(slots) != 1)
                    or (index >= end_index and slots)
                ):
                    raise UnknownPageStateError("Kadocomi content-first final PR spread shape changed")
            elif (
                (index == 0 and len(slots) != 1)
                or (0 < index < end_index - 1 and len(slots) != 2)
                or (index == end_index - 1 and len(slots) != 1)
                or (index >= end_index and slots)
            ):
                raise UnknownPageStateError("Kadocomi mixed-final content or END slide shape changed")
            canvas_boxes: list[dict[str, object]] = []
            for slot, canvas in zip(slots, canvases, strict=True):
                if not isinstance(canvas, dict) or canvas.get("slot") != slot:
                    raise UnknownPageStateError("Kadocomi canvas identity is ambiguous")
                box = canvas.get("box")
                if not isinstance(box, dict):
                    raise UnknownPageStateError("Kadocomi canvas geometry is missing")
                canvas_boxes.append(box)
            if len(canvas_boxes) == 2:
                right_x = canvas_boxes[0].get("x")
                left_x = canvas_boxes[1].get("x")
                if not isinstance(right_x, (int, float)) or not isinstance(left_x, (int, float)) or right_x <= left_x:
                    raise UnknownPageStateError("Kadocomi RTL spread slot order is unknown")
            slide_slots.append(tuple(slots))
            flattened.extend(slots)
        if len(flattened) > MAX_CANVAS_SLOTS or len(flattened) != len(set(flattened)):
            raise UnknownPageStateError("Kadocomi content canvas inventory is duplicated or too large")
        if layout in {
            _BEGINNING_PR_PAIRED_LAYOUT,
            _BEGINNING_PR_MIXED_FINAL_LAYOUT,
            _BEGINNING_PR_FINAL_PR_LAYOUT,
        }:
            if slide_slots[0] or any(not slide_slots[index] for index in range(1, end_index)):
                raise UnknownPageStateError("Kadocomi beginning PR layout has an unexplained empty slide")
        elif any(not slide_slots[index] for index in range(
            end_index - 1 if layout in _PR_END_LAYOUTS else end_index
        )):
            raise UnknownPageStateError("Kadocomi content inventory has an unexplained empty slide")
        return tuple(flattened), tuple(slide_slots), end_index, layout

    async def _advance_beginning_pr_entry(self, page: Page) -> None:
        self._validate_current_episode_url(page)
        await self._validate_episode_metadata(page)
        snapshot = await self._snapshot(page)
        slots, slide_slots, end_index, layout = self._validate_inventory(snapshot)
        if (
            slots != self._all_slots
            or slide_slots != self._slide_slots
            or end_index != self._end_slide_index
            or layout not in {
                _BEGINNING_PR_PAIRED_LAYOUT,
                _BEGINNING_PR_MIXED_FINAL_LAYOUT,
                _BEGINNING_PR_FINAL_PR_LAYOUT,
            }
            or snapshot.get("activeIndex") != 0
        ):
            raise UnknownPageStateError("Kadocomi beginning PR entry changed before navigation")
        try:
            if layout == _BEGINNING_PR_FINAL_PR_LAYOUT:
                target = await page.evaluate(
                    _BEGINNING_PR_FINAL_PR_ARROW_SAFE_SCRIPT,
                    {"endIndex": end_index},
                )
            else:
                target = await page.evaluate(_BEGINNING_PR_ARROW_SAFE_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi beginning PR keyboard target could not be verified") from exc
        if not isinstance(target, dict) or target.get("ok") is not True or target.get("activeIndex") != 0:
            reason = target.get("reason") if isinstance(target, dict) else "malformed_result"
            raise UnknownPageStateError(f"Kadocomi beginning PR ArrowLeft target is unsafe: {reason}")
        self._pending_next_index = 0
        try:
            await page.keyboard.press("ArrowLeft")
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi beginning PR could not advance to its first content slide") from exc
        await self.wait_for_change(page, None)
        self._validate_current_episode_url(page)
        await self._validate_episode_metadata(page)
        settled = await self._snapshot(page)
        settled_slots, settled_slides, settled_end, settled_layout = self._validate_inventory(settled)
        if (
            settled_slots != self._all_slots
            or settled_slides != self._slide_slots
            or settled_end != self._end_slide_index
            or settled_layout != layout
            or settled.get("activeIndex") != 1
        ):
            raise UnknownPageStateError("Kadocomi beginning PR did not advance to the exact first content slide")

    async def _wait_for_initial_reader(self, page: Page) -> None:
        deadline = asyncio.get_running_loop().time() + VIEWER_READY_TIMEOUT_SECONDS
        previous: tuple[object, ...] | None = None
        self._validate_current_episode_url(page)
        while asyncio.get_running_loop().time() < deadline:
            snapshot = await self._snapshot(page)
            if snapshot.get("status") in {
                "clones", "nested_carousel", "direction", "slides",
                "content_wrapper_shape", "end_marker_shape",
            }:
                raise UnknownPageStateError("Kadocomi initial viewer variant is unsupported")
            if snapshot.get("status") == "ok":
                rows = snapshot.get("slideRows")
                has_content_slots = isinstance(rows, list) and any(
                    isinstance(row, dict)
                    and isinstance(row.get("contentSlots"), list)
                    and bool(row["contentSlots"])
                    for row in rows
                )
                if snapshot.get("endMarkerCount") == 0 or not has_content_slots:
                    previous = None
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                slots, slide_slots, end_index, layout = self._validate_inventory(snapshot)
                if snapshot.get("activeIndex") != 0:
                    raise UnknownPageStateError("Kadocomi episode did not open at its first reader slide")
                if layout in {
                    _BEGINNING_PR_PAIRED_LAYOUT,
                    _BEGINNING_PR_MIXED_FINAL_LAYOUT,
                    _BEGINNING_PR_FINAL_PR_LAYOUT,
                }:
                    ready = True
                else:
                    first_canvas = snapshot["slideRows"][0]["contentCanvases"][0]
                    last = first_canvas.get("last") if isinstance(first_canvas, dict) else None
                    ready = (
                        isinstance(last, dict)
                        and last.get("sourceTag") == "IMG"
                        and last.get("complete") is True
                        and last.get("blobAvailable") is True
                        and isinstance(first_canvas.get("width"), int)
                        and first_canvas["width"] > 0
                        and isinstance(first_canvas.get("height"), int)
                        and first_canvas["height"] > 0
                    )
                signature = _snapshot_signature(
                    snapshot,
                    include_pr_markers=layout in _TRACKED_PR_LAYOUTS,
                )
                if ready and signature and signature == previous:
                    self._all_slots = slots
                    self._slide_slots = slide_slots
                    self._end_slide_index = end_index
                    self._reader_layout = layout
                    return
                previous = signature if ready else None
            else:
                previous = None
            await page.wait_for_timeout(VIEWER_POLL_MS)
        raise PageChangeTimeoutError("Kadocomi first reader slide did not settle")

    async def detect_state(self, page: Page) -> PageState:
        self._validate_current_episode_url(page)
        snapshot = await self._snapshot(page)
        if snapshot.get("status") in {"content_wrapper_shape", "end_marker_shape"}:
            raise UnknownPageStateError("Kadocomi reader wrapper or END marker shape changed")
        if snapshot.get("status") != "ok":
            return PageState.LOADING
        slots, slide_slots, end_index, layout = self._validate_inventory(snapshot)
        if (
            slots != self._all_slots
            or slide_slots != self._slide_slots
            or end_index != self._end_slide_index
            or layout != self._reader_layout
        ):
            raise UnknownPageStateError("Kadocomi reader canvas inventory changed during capture")
        active_index = snapshot.get("activeIndex")
        if isinstance(active_index, bool) or not isinstance(active_index, int):
            raise UnknownPageStateError("Kadocomi active slide index is invalid")
        if self._reader_layout in {
            _BEGINNING_PR_PAIRED_LAYOUT,
            _BEGINNING_PR_MIXED_FINAL_LAYOUT,
            _BEGINNING_PR_FINAL_PR_LAYOUT,
        } and active_index == 0:
            raise UnknownPageStateError("Kadocomi beginning PR slide was not advanced during initialization")
        if active_index == self._end_slide_index:
            if not self._is_verified_terminal(snapshot, slide_slots, end_index):
                raise UnknownPageStateError("Kadocomi reached END before all exact content slots were captured")
            self._ended = True
            return PageState.END
        if active_index < 0 or active_index >= (self._end_slide_index or 0):
            raise UnknownPageStateError("Kadocomi active slide is outside the verified content sequence")
        current_slots = slide_slots[active_index]
        already_captured = (
            current_slots == self._last_capture_slots
            and bool(current_slots)
            and tuple(self._captured_slots[-len(current_slots) :]) == current_slots
        )
        expected_prefix = tuple(self._all_slots[: len(self._captured_slots)])
        next_slots = tuple(self._all_slots[len(self._captured_slots) : len(self._captured_slots) + len(current_slots)])
        if (
            tuple(self._captured_slots) != expected_prefix
            or not current_slots
            or (already_captured and tuple(self._captured_slots[-len(current_slots) :]) != current_slots)
            or (not already_captured and current_slots != next_slots)
        ):
            raise UnknownPageStateError("Kadocomi active canvas slots skipped or repeated content")
        row = snapshot["slideRows"][active_index]
        canvases = row.get("contentCanvases")
        if not isinstance(canvases, list) or len(canvases) != len(current_slots):
            return PageState.LOADING
        for canvas in canvases:
            last = canvas.get("last") if isinstance(canvas, dict) else None
            if (
                not isinstance(last, dict)
                or last.get("sourceTag") != "IMG"
                or last.get("complete") is not True
                or (last.get("blobAvailable") is not True and not already_captured)
                or not isinstance(canvas.get("width"), int)
                or canvas["width"] <= 0
                or not isinstance(canvas.get("height"), int)
                or canvas["height"] <= 0
            ):
                return PageState.LOADING
        return PageState.CONTENT

    def _is_verified_terminal(
        self,
        snapshot: dict[str, Any],
        slide_slots: tuple[tuple[str, ...], ...],
        end_index: int,
    ) -> bool:
        if (
            self._reader_layout not in {
                _PAIRED_END_LAYOUT,
                _MIXED_FINAL_END_LAYOUT,
                _BEGINNING_PR_PAIRED_LAYOUT,
                _BEGINNING_PR_MIXED_FINAL_LAYOUT,
                _BEGINNING_PR_FINAL_PR_LAYOUT,
                _CONTENT_FIRST_FINAL_PR_LAYOUT,
                _PAIRED_FIRST_DOUBLE_END_LAYOUT,
                _PAIRED_FIRST_FINAL_PR_LAYOUT,
                _PAIRED_FIRST_PR_END_LAYOUT,
                _DIRECT_FIRST_FINAL_PR_LAYOUT,
                _DIRECT_FIRST_PR_END_LAYOUT,
            }
            or tuple(self._captured_slots) != self._all_slots
            or end_index != self._end_slide_index
            or not 0 <= end_index < len(slide_slots)
            or slide_slots[end_index]
            or snapshot.get("activeIndex") != end_index
        ):
            return False
        indexes = snapshot.get("markerSlideIndexes")
        numbers = snapshot.get("markerNumbers")
        if not isinstance(indexes, list) or not isinstance(numbers, list):
            return False
        if self._reader_layout == _PAIRED_FIRST_DOUBLE_END_LAYOUT:
            return (
                indexes == [end_index, end_index, end_index + 1, end_index + 1]
                and numbers == ["1", "2", "1", "2"]
                and len(slide_slots) == end_index + 2
                and not slide_slots[end_index + 1]
            )
        if self._reader_layout in {
            _PAIRED_END_LAYOUT,
            _BEGINNING_PR_PAIRED_LAYOUT,
            _BEGINNING_PR_FINAL_PR_LAYOUT,
            _CONTENT_FIRST_FINAL_PR_LAYOUT,
            _PAIRED_FIRST_FINAL_PR_LAYOUT,
            _DIRECT_FIRST_FINAL_PR_LAYOUT,
        }:
            return indexes == [end_index, end_index] and numbers == ["1", "2"]
        return (
            indexes == [end_index - 1, end_index, end_index]
            and numbers == ["2", "1", "2"]
            and (bool(slide_slots[end_index - 1]) or self._reader_layout in _PR_END_LAYOUTS)
        )

    async def get_capture_target(self, page: Page) -> Locator:
        del page
        raise UnknownPageStateError("Kadocomi requires proven native WebP capture")

    async def get_capture_targets(self, page: Page) -> tuple[Locator, ...]:
        del page
        raise UnknownPageStateError("Kadocomi does not permit locator or screenshot fallback")

    async def capture_page(self, page: Page) -> tuple[CaptureResult, ...] | None:
        self._validate_current_episode_url(page)
        await self._validate_episode_metadata(page)
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi has no verified active content slide")
        snapshot = await self._snapshot(page)
        active_index = snapshot.get("activeIndex")
        if not isinstance(active_index, int) or isinstance(active_index, bool):
            raise UnknownPageStateError("Kadocomi active slide identity is missing")
        expected_slots = self._slide_slots[active_index]
        if expected_slots == self._last_capture_slots or any(
            slot in self._captured_slots for slot in expected_slots
        ):
            raise UnknownPageStateError("Kadocomi active slot set was already captured")
        track_pr_markers = self._reader_layout in _TRACKED_PR_LAYOUTS
        pr_signature_before = _pr_marker_signature(snapshot) if track_pr_markers else None
        try:
            raw = await asyncio.wait_for(
                page.evaluate(
                    NATIVE_CAPTURE_SCRIPT,
                    {
                        "expectedSlots": list(expected_slots),
                        "maxBytes": MAX_NATIVE_BLOB_BYTES,
                        "maxPixels": MAX_NATIVE_PIXEL_COUNT,
                        "maxTotalPixels": MAX_NATIVE_TOTAL_PIXEL_COUNT,
                        "trackPrMarkers": track_pr_markers,
                    },
                ),
                timeout=10,
            )
        except (PlaywrightError, TimeoutError) as exc:
            self._capture_diagnostics = {"mode": "capture_failed", "reason": "native_proof_timeout"}
            raise UnknownPageStateError("Kadocomi native capture proof did not complete") from exc
        if not isinstance(raw, dict) or raw.get("ok") is not True:
            reason = raw.get("reason") if isinstance(raw, dict) else "malformed_result"
            self._capture_diagnostics = {"mode": "capture_failed", "reason": str(reason)}
            raise UnknownPageStateError("Kadocomi native source proof failed closed")
        captures_raw = raw.get("captures")
        if not isinstance(captures_raw, list) or len(captures_raw) != len(expected_slots):
            raise UnknownPageStateError("Kadocomi native capture set is incomplete")
        results: list[CaptureResult] = []
        for expected_slot, row in zip(expected_slots, captures_raw, strict=True):
            if (
                not isinstance(row, dict)
                or row.get("slot") != expected_slot
                or not isinstance(row.get("data"), str)
                or not isinstance(row.get("mimeType"), str)
                or isinstance(row.get("width"), bool)
                or not isinstance(row.get("width"), int)
                or isinstance(row.get("height"), bool)
                or not isinstance(row.get("height"), int)
            ):
                raise UnknownPageStateError("Kadocomi native capture result is malformed")
            try:
                data = base64.b64decode(row["data"], validate=True)
            except (ValueError, TypeError) as exc:
                raise UnknownPageStateError("Kadocomi native Blob bytes are malformed") from exc
            result = capture_kadocomi_webp(
                data,
                source_mime_type=row["mimeType"],
                width=row["width"],
                height=row["height"],
            )
            if result is None:
                raise UnknownPageStateError("Kadocomi original viewer Blob is not a supported WebP")
            results.append(result)
        self._validate_current_episode_url(page)
        await self._validate_episode_metadata(page)
        after = await self._snapshot(page)
        after_slots, after_slides, after_end_index, after_layout = self._validate_inventory(after)
        if (
            after_slots != self._all_slots
            or after_slides != self._slide_slots
            or after_end_index != self._end_slide_index
            or after_layout != self._reader_layout
            or after.get("activeIndex") != active_index
            or (
                track_pr_markers
                and _pr_marker_signature(after) != pr_signature_before
            )
        ):
            raise UnknownPageStateError("Kadocomi active slide or tracked PR markers changed after native byte transfer")
        self._captured_slots.extend(expected_slots)
        self._last_capture_slots = expected_slots
        self._capture_diagnostics = {
            "mode": "verified_viewer_source_webp",
            "slots": list(expected_slots),
            "output_dimensions": [[result.width, result.height] for result in results],
            "output_formats": [result.mime_type for result in results],
        }
        return tuple(results)

    async def get_content_identity(self, page: Page) -> ContentIdentity:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi content identity is unavailable")
        snapshot = await self._snapshot(page)
        active_index = snapshot["activeIndex"]
        slots = self._slide_slots[active_index]
        return ContentIdentity(
            page_id=",".join(slots),
            page_number=len(self._captured_slots) + 1,
            source_id=self._external_id,
        )

    async def get_content_context(self, page: Page) -> ContentContext:
        self._validate_current_episode_url(page)
        if self._work_title is None or self._work_id is None or self._episode_id is None:
            raise UnknownPageStateError("Kadocomi work context has not been verified")
        return ContentContext(
            content_id=self._episode_id,
            work_id=self._work_id,
            episode_id=self._episode_id,
            title=self._work_title,
        )

    async def go_next(self, page: Page) -> None:
        if await self.detect_state(page) is not PageState.CONTENT:
            raise UnknownPageStateError("Kadocomi cannot advance from a non-content state")
        snapshot = await self._snapshot(page)
        slots, slide_slots, end_index, layout = self._validate_inventory(snapshot)
        active_index = snapshot.get("activeIndex")
        if (
            slots != self._all_slots
            or slide_slots != self._slide_slots
            or end_index != self._end_slide_index
            or layout != self._reader_layout
            or not isinstance(active_index, int)
            or isinstance(active_index, bool)
            or self._pending_next_index is not None
            or self._last_capture_slots != self._slide_slots[active_index]
            or tuple(self._captured_slots[-len(self._last_capture_slots) :]) != self._last_capture_slots
        ):
            raise UnknownPageStateError("Kadocomi page turn is not bound to the last native capture")
        is_mixed_final_turn = (
            self._reader_layout in {
                _MIXED_FINAL_END_LAYOUT,
                _BEGINNING_PR_MIXED_FINAL_LAYOUT,
            }
            and self._end_slide_index is not None
            and active_index == self._end_slide_index - 1
        )
        if self._reader_layout in _DIRECT_FIRST_LAYOUTS and active_index == 0:
            target = await page.evaluate(_DIRECT_FIRST_ARROW_SAFE_SCRIPT)
            if not isinstance(target, dict) or target.get("ok") is not True:
                raise UnknownPageStateError("Kadocomi direct first canvas keyboard target is unsafe")
            await page.keyboard.press("ArrowLeft")
            self._pending_next_index = 0
            return
        is_beginning_final_pr_turn = (
            self._reader_layout == _BEGINNING_PR_FINAL_PR_LAYOUT
            and self._end_slide_index is not None
            and active_index == self._end_slide_index - 1
        )
        is_content_first_final_pr_turn = (
            self._reader_layout in _TRACKED_PR_LAYOUTS - _PR_END_LAYOUTS
            and self._end_slide_index is not None
            and active_index == self._end_slide_index - 1
        )
        if is_mixed_final_turn:
            if tuple(self._captured_slots) != self._all_slots or len(self._last_capture_slots) != 1:
                raise UnknownPageStateError("Kadocomi mixed-final END is not bound to the final exact slot")
            try:
                target = await page.evaluate(
                    _MIXED_FINAL_ARROW_SAFE_SCRIPT,
                    {"activeIndex": active_index, "slotCount": len(self._last_capture_slots)},
                )
            except PlaywrightError as exc:
                raise UnknownPageStateError("Kadocomi mixed-final key target could not be verified") from exc
            if (
                not isinstance(target, dict)
                or target.get("ok") is not True
                or target.get("activeIndex") != active_index
                or target.get("slotCount") != 1
            ):
                raise UnknownPageStateError("Kadocomi mixed-final END key target is unsafe")
            await page.keyboard.press("ArrowLeft")
            self._pending_next_index = active_index
            return
        if is_content_first_final_pr_turn:
            if tuple(self._captured_slots) != self._all_slots or len(self._last_capture_slots) != 1:
                raise UnknownPageStateError("Kadocomi content-first final PR turn is not bound to its last slot")
            try:
                target = await page.evaluate(
                    (
                        _PAIRED_FIRST_PR_ARROW_SAFE_SCRIPT
                        if self._reader_layout in {_PAIRED_FIRST_DOUBLE_END_LAYOUT, _PAIRED_FIRST_FINAL_PR_LAYOUT, _DIRECT_FIRST_FINAL_PR_LAYOUT}
                        else _CONTENT_FIRST_FINAL_PR_ARROW_SAFE_SCRIPT
                    ),
                    {"endIndex": self._end_slide_index,
                     "doubleEnd": self._reader_layout == _PAIRED_FIRST_DOUBLE_END_LAYOUT,
                     "directFirst": self._reader_layout == _DIRECT_FIRST_FINAL_PR_LAYOUT},
                )
            except PlaywrightError as exc:
                raise UnknownPageStateError("Kadocomi final PR ArrowLeft target could not be verified") from exc
            if (
                not isinstance(target, dict)
                or target.get("ok") is not True
                or target.get("activeIndex") != active_index
                or target.get("slotCount") != 1
            ):
                reason = target.get("reason") if isinstance(target, dict) else "malformed_result"
                raise UnknownPageStateError(f"Kadocomi final PR ArrowLeft target is unsafe: {reason}")
            # Require the next exact paired END; PR wrappers never establish completion.
            await page.keyboard.press("ArrowLeft")
            self._pending_next_index = active_index
            return
        if is_beginning_final_pr_turn:
            if tuple(self._captured_slots) != self._all_slots or len(self._last_capture_slots) != 1:
                raise UnknownPageStateError("Kadocomi final PR turn is not bound to the final exact slot")
            try:
                target = await page.evaluate(
                    _BEGINNING_PR_FINAL_PR_FINAL_ARROW_SAFE_SCRIPT,
                    {
                        "activeIndex": active_index,
                        "endIndex": self._end_slide_index,
                        "slotCount": len(self._last_capture_slots),
                    },
                )
            except PlaywrightError as exc:
                raise UnknownPageStateError("Kadocomi final PR key target could not be verified") from exc
            if (
                not isinstance(target, dict)
                or target.get("ok") is not True
                or target.get("activeIndex") != active_index
                or target.get("slotCount") != 1
            ):
                raise UnknownPageStateError("Kadocomi final PR ArrowLeft target is unsafe")
            # This PR n=2 belongs to the final content spread; only the next paired END ends the episode.
            await page.keyboard.press("ArrowLeft")
            self._pending_next_index = active_index
            return
        try:
            target = await page.evaluate(_NAVIGATION_TARGET_SCRIPT)
        except PlaywrightError as exc:
            raise UnknownPageStateError("Kadocomi reader overlay hit test failed") from exc
        if (
            not isinstance(target, dict)
            or target.get("ok") is not True
            or target.get("activeIndex") != active_index
            or target.get("slotCount") != len(self._last_capture_slots)
            or not isinstance(target.get("x"), (int, float))
            or not isinstance(target.get("y"), (int, float))
        ):
            raise UnknownPageStateError("Kadocomi verified left reader overlay is unavailable")
        await page.mouse.click(target["x"], target["y"])
        self._pending_next_index = active_index

    async def wait_for_change(
        self,
        page: Page,
        previous_identity: ContentIdentity | None,
    ) -> None:
        del previous_identity
        if self._pending_next_index is None:
            raise PageChangeTimeoutError("Kadocomi has no verified page-turn action pending")
        previous_index = self._pending_next_index
        deadline = asyncio.get_running_loop().time() + PAGE_CHANGE_TIMEOUT_SECONDS
        previous_signature: tuple[object, ...] | None = None
        stable = 0
        try:
            while asyncio.get_running_loop().time() < deadline:
                self._validate_current_episode_url(page)
                snapshot = await self._snapshot(page)
                if snapshot.get("status") in {"content_wrapper_shape", "end_marker_shape"}:
                    raise UnknownPageStateError("Kadocomi reader wrapper or END marker shape changed")
                if snapshot.get("status") != "ok":
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                slots, slide_slots, end_index, layout = self._validate_inventory(snapshot)
                if (
                    slots != self._all_slots
                    or slide_slots != self._slide_slots
                    or end_index != self._end_slide_index
                    or layout != self._reader_layout
                ):
                    raise UnknownPageStateError("Kadocomi page turn changed the content inventory")
                active_index = snapshot.get("activeIndex")
                if active_index == previous_index:
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                if active_index != previous_index + 1:
                    raise UnknownPageStateError("Kadocomi page turn skipped a reader slide")
                if layout in _PR_END_LAYOUTS and active_index == end_index - 1:
                    if tuple(self._captured_slots) != self._all_slots:
                        raise UnknownPageStateError("Kadocomi PR/END bridge reached before all content")
                    signature = _snapshot_signature(snapshot, include_pr_markers=True)
                    if signature and signature == previous_signature:
                        await self._validate_episode_metadata(page)
                        target = await page.evaluate(
                            _PAIRED_FIRST_PR_ARROW_SAFE_SCRIPT,
                            {"endIndex": end_index, "bridge": True,
                             "directFirst": layout == _DIRECT_FIRST_PR_END_LAYOUT},
                        )
                        if (
                            not isinstance(target, dict) or target.get("ok") is not True
                            or target.get("activeIndex") != active_index or target.get("slotCount") != 0
                        ):
                            raise UnknownPageStateError("Kadocomi PR/END bridge keyboard target is unsafe")
                        await page.keyboard.press("ArrowLeft")
                        previous_index = active_index
                        self._pending_next_index = active_index
                        previous_signature = None
                    else:
                        previous_signature = signature
                    await page.wait_for_timeout(VIEWER_POLL_MS)
                    continue
                if active_index == self._end_slide_index:
                    if not self._is_verified_terminal(snapshot, slide_slots, end_index):
                        raise UnknownPageStateError("Kadocomi terminal slide is not a complete explicit END")
                    self._pending_next_index = None
                    return
                row = snapshot["slideRows"][active_index]
                canvases = row["contentCanvases"]
                ready = all(
                    isinstance(canvas.get("last"), dict)
                    and canvas["last"].get("sourceTag") == "IMG"
                    and canvas["last"].get("complete") is True
                    and canvas["last"].get("blobAvailable") is True
                    and isinstance(canvas.get("width"), int)
                    and canvas["width"] > 0
                    and isinstance(canvas.get("height"), int)
                    and canvas["height"] > 0
                    for canvas in canvases
                    if isinstance(canvas, dict)
                ) and len(canvases) == len(slide_slots[active_index])
                signature = _snapshot_signature(
                    snapshot,
                    include_pr_markers=self._reader_layout in _TRACKED_PR_LAYOUTS,
                )
                if ready and signature and signature == previous_signature:
                    stable += 1
                    if stable >= 1:
                        self._pending_next_index = None
                        return
                else:
                    stable = 0
                previous_signature = signature if ready else None
                await page.wait_for_timeout(VIEWER_POLL_MS)
        except UnknownPageStateError as exc:
            self._capture_diagnostics = {
                "mode": "page_change_failed",
                "reason": str(exc),
            }
            raise
        raise PageChangeTimeoutError("Kadocomi next reader slide did not settle")

    async def collect_debug_metadata(self, page: Page) -> dict[str, object]:
        del page
        return {"kadocomi_capture": dict(self._capture_diagnostics)}

    def get_output_metadata(self) -> dict[str, str | None]:
        return {"title": self._work_title, "order": self._order_label}


__all__ = ["KadocomiAdapter"]
