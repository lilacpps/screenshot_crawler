"""Bounded Comic DAYS C1 access/listing reconnaissance.

The probe only observes the public series page and episode pages.  It never
clicks ticket, point, coin, purchase, login, or next-episode controls and does
not retain response bodies or signed URLs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

try:
    from poc.comicdays_probe import redact_metadata, redact_url
except ModuleNotFoundError:  # direct ``python poc/script.py`` execution
    from comicdays_probe import redact_metadata, redact_url
from screenshot_crawler.core.browser import BrowserSession, resolve_cdp_endpoint

DEFAULT_URL = "https://comic-days.com/volume/12207421984152339784"
DEFAULT_OUTPUT_DIR = Path("output/comicdays_c1_access_probe")
EVAL_TIMEOUT_SECONDS = 8
PROBE_TIMEOUT_SECONDS = 45
MAX_RECORDS = 200


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize_json(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Keep access-relevant metadata while dropping URLs and image payloads."""

    if depth > 8:
        return {"type": type(value).__name__}
    lowered = key.lower()
    sensitive_keys = {
        "access_token", "api_key", "authorization", "cookie", "credential",
        "password", "secret", "signature", "signed_url", "token",
    }
    if isinstance(value, dict):
        return {
            str(name): summarize_json(child, key=str(name), depth=depth + 1)
            for name, child in list(value.items())[:300]
            if str(name).lower() not in {
                "url", "src", "image", "thumbnail", "body", *sensitive_keys
            }
        }
    if isinstance(value, list):
        return [summarize_json(child, key=key, depth=depth + 1) for child in value[:200]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, str):
        if any(term in lowered for term in ("access", "free", "ticket", "point", "price", "episode", "product", "title", "name", "id", "order", "status")):
            return value[:300]
        return {"type": "str", "length": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
    return {"type": type(value).__name__}


def parse_atom_entries(body: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(body)
    entries: list[dict[str, Any]] = []
    for entry in list(root):
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        fields: dict[str, Any] = {}
        for child in list(entry):
            name = child.tag.rsplit("}", 1)[-1]
            if name in {"id", "title", "updated", "published"}:
                fields[name] = (child.text or "").strip()[:300]
            elif name == "link" and child.attrib.get("href"):
                href = child.attrib["href"]
                if "/episode/" in href or "link" not in fields:
                    fields["link"] = redact_url(href)
        entries.append(fields)
    return entries[:200]


async def bounded_eval(page: Any, expression: str) -> Any:
    return await asyncio.wait_for(page.evaluate(expression), timeout=EVAL_TIMEOUT_SECONDS)


async def collect_page(page: Any) -> dict[str, Any]:
    return await bounded_eval(
        page,
        """() => {
          const visible = element => {
            if (!element) return false;
            const r = element.getBoundingClientRect();
            const s = getComputedStyle(element);
            return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const attrs = element => Object.fromEntries(
            [...element.attributes].map(item => [item.name, item.value])
          );
          const clean = value => (value || '').replace(/\\s+/g, ' ').trim();
          const episodeLinks = [...document.querySelectorAll('a[href*="/episode/"]')]
            .slice(0, 200).map((link, index) => {
              let parent = link;
              const parents = [];
              for (let level = 0; level < 4 && parent; level += 1) {
                parent = parent.parentElement;
                if (parent) parents.push({
                  tag: parent.tagName.toLowerCase(), id: parent.id || null,
                  class: parent.getAttribute('class'), text: clean(parent.innerText).slice(0, 700),
                  attrs: attrs(parent),
                });
              }
              return {
                index, href: link.href, text: clean(link.innerText).slice(0, 300),
                class: link.getAttribute('class'), id: link.id || null,
                visible: visible(link), attrs: attrs(link), parents,
              };
            });
          const accessNodes = [...document.querySelectorAll('body *')]
            .filter(element => /無料|チケット|ポイント|コイン|有料|購入|ログイン/.test(clean(element.innerText)))
            .slice(0, 200).map(element => ({
              tag: element.tagName.toLowerCase(), id: element.id || null,
              class: element.getAttribute('class'), text: clean(element.innerText).slice(0, 500),
              visible: visible(element), attrs: attrs(element),
            }));
          const dataEndpoints = [...document.querySelectorAll('*')]
            .flatMap(element => [...element.attributes].map(attr => ({
              name: attr.name, value: attr.value,
            })))
            .filter(item => /endpoint|json|api|rss|atom/i.test(item.name + item.value))
            .slice(0, 200);
          return {
            url: location.href,
            title: document.title,
            body_text: clean(document.body?.innerText).slice(0, 8000),
            html_length: document.documentElement?.outerHTML?.length || 0,
            episode_links: episodeLinks,
            access_nodes: accessNodes,
            data_endpoints: dataEndpoints,
          };
        }""",
    )


async def _run(url: str, output_dir: Path, endpoint: str | None) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    session = await BrowserSession.connect(resolve_cdp_endpoint(cli_endpoint=endpoint))
    page = await session.new_page()
    requests: list[dict[str, Any]] = []

    def on_request(request: Any) -> None:
        parsed = urlsplit(request.url)
        if parsed.netloc not in {"comic-days.com", "cdn.comic-days.com", "cdn-img.comic-days.com"}:
            return
        if len(requests) >= MAX_RECORDS:
            return
        query_pairs = [
            (part.split("=", 1)[0], part.split("=", 1)[1] if "=" in part else "")
            for part in parsed.query.split("&")
            if part
        ]
        safe_query_values = {
            key: value[:80]
            for key, value in query_pairs
            if key in {"free_only", "type"}
            or (key in {"aggregate_id", "readable_product_id"} and value.isdigit())
        }
        requests.append(
            {
                "method": request.method,
                "resource_type": request.resource_type,
                "url": redact_url(request.url),
                "path": parsed.path,
                "query_key_count": len([part for part in parsed.query.split("&") if part]),
                "query_keys": [part.split("=", 1)[0] for part in parsed.query.split("&") if part][:30],
                "safe_query_values": safe_query_values,
            }
        )

    page.on("request", on_request)
    try:
        await page.goto(url, wait_until="commit", timeout=30_000)
        await page.wait_for_timeout(4_000)
        page_data = await collect_page(page)
        volume_json: dict[str, Any] = {}
        free_atom: dict[str, Any] = {}
        volume_endpoint = next(
            (
                item.get("value")
                for item in page_data.get("data_endpoints", [])
                if item.get("name") == "data-json-url" and "/volume/" in str(item.get("value"))
            ),
            None,
        )
        if volume_endpoint:
            try:
                response = await asyncio.wait_for(
                    page.request.get(volume_endpoint, timeout=5_000), timeout=8
                )
                body = await asyncio.wait_for(response.body(), timeout=5)
                parsed = json.loads(body.decode("utf-8"))
                volume_json = {
                    "endpoint": redact_url(volume_endpoint),
                    "status": response.status,
                    "body_length": len(body),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "json_summary": summarize_json(parsed),
                }
            except Exception as exc:  # noqa: BLE001 - preserve bounded evidence
                volume_json = {
                    "endpoint": redact_url(volume_endpoint),
                    "error": {"type": type(exc).__name__, "message": str(exc)[:300]},
                }
        try:
            series_id = next(
                (
                    str(item.get("value")).rsplit("/", 1)[-1]
                    for item in page_data.get("data_endpoints", [])
                    if item.get("name") == "href" and "/atom/series/" in str(item.get("value"))
                ),
                None,
            )
            if series_id and series_id.isdigit():
                atom_url = f"https://comic-days.com/atom/series/{series_id}?free_only=1"
                response = await asyncio.wait_for(
                    page.request.get(atom_url, timeout=5_000), timeout=8
                )
                body = await asyncio.wait_for(response.body(), timeout=5)
                entries = parse_atom_entries(body)
                free_atom = {
                    "endpoint": redact_url(atom_url),
                    "status": response.status,
                    "content_type": response.headers.get("content-type", "").split(";", 1)[0],
                    "body_length": len(body),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "entry_count": len(entries),
                    "entries": entries,
                }
        except Exception as exc:  # noqa: BLE001 - preserve bounded evidence
            free_atom = {"error": {"type": type(exc).__name__, "message": str(exc)[:300]}}
        report = {
            "probe": "comicdays_c1_access_probe",
            "started_at": datetime.now(UTC).isoformat(),
            "target_url": redact_url(url),
            "final_url": redact_url(page.url),
            "page": await redact_metadata(page_data),
            "volume_json": volume_json,
            "free_atom": free_atom,
            "requests": requests,
            "request_count": len(requests),
        }
        write_json(output_dir / "report.json", report)
    finally:
        await session.close_page(page)
        await session.close()


async def run(url: str, output_dir: Path, endpoint: str | None) -> None:
    try:
        async with asyncio.timeout(PROBE_TIMEOUT_SECONDS):
            await _run(url, output_dir, endpoint)
    except TimeoutError:
        write_json(
            output_dir / "report.json",
            {
                "probe": "comicdays_c1_access_probe",
                "target_url": redact_url(url),
                "error": {"type": "ProbeTimeout", "timeout_seconds": PROBE_TIMEOUT_SECONDS},
            },
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cdp-endpoint")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(run(args.url, args.output_dir, args.cdp_endpoint))
