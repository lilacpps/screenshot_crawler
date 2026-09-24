"""Summarize observation-only Jump+ Discovery probe reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SAMPLES = {
    "baseline": "https://shonenjumpplus.com/episode/13932016480029111789",
    "manual_rental_series": "https://shonenjumpplus.com/episode/9253191254047172892",
    "normal": "https://shonenjumpplus.com/episode/9253191256637716556",
    "ultra_long": "https://shonenjumpplus.com/episode/10833519556325021794",
}


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def pagination_offsets(report: dict[str, Any]) -> list[int]:
    offsets: set[int] = set()
    for record in report.get("network_observation", {}).get("additional_after_initial_load", []):
        url = str(record.get("url") or "")
        if "pagination_readable_products" not in url:
            continue
        raw = parse_qs(urlparse(url).query).get("offset", [])
        if raw and raw[0].isdigit():
            offsets.add(int(raw[0]))
    return sorted(offsets)


def summarize_report(name: str, report: dict[str, Any]) -> dict[str, Any]:
    initial_control = report.get("initial_range", {}).get("control") or {}
    ranges = report.get("ranges", [])
    work = report.get("work") or {}
    gtm_episode = (report.get("embedded_data", {}).get("gtm_data_layer") or {}).get("episode", {})
    return {
        "sample": name,
        "target_url": report.get("target_url"),
        "work": {
            "title": work.get("title"),
            "author": work.get("author"),
            "series_id": gtm_episode.get("series_id"),
            "target_episode_id": report.get("target_episode_id"),
        },
        "scope": {
            "variant": (report.get("dom_mutation_observation", {}).get("initial_scope") or {}).get("variant"),
            "listing_selector": (report.get("dom_mutation_observation", {}).get("initial_listing_container") or {}).get("selector"),
        },
        "initial_selected_range": initial_control.get("text"),
        "range_count": len(ranges),
        "ranges": [
            {
                "index": item.get("index"),
                "label": item.get("label"),
                "parsed_label": item.get("parsed_label"),
                "initial_episode_count": item.get("initial_episode_count"),
                "final_episode_count": item.get("final_episode_count"),
                "more_click_count": item.get("more_click_count"),
                "incomplete": item.get("incomplete"),
            }
            for item in ranges
        ],
        "episode_count": report.get("unique_episode_count"),
        "duplicate_episode_ids": report.get("duplicate_episode_ids", []),
        "ordering": report.get("ordering", {}),
        "access_states": report.get("distinct_access_states", []),
        "network_pagination_offsets": pagination_offsets(report),
        "manual_rental": report.get("manual_rental", {}),
        "network_episode_state_count": len(report.get("network_episode_states", [])),
    }


def build_comparison(input_dir: Path) -> dict[str, Any]:
    samples: dict[str, Any] = {}
    for name, url in SAMPLES.items():
        report = load_report(input_dir / name / "report.json")
        if report.get("target_url") != url:
            raise ValueError(f"{name}: target URL does not match matrix manifest")
        samples[name] = summarize_report(name, report)
    return {
        "schema": "jumpplus-discovery-j0-matrix-v1",
        "samples": samples,
        "facts": [
            "The same observation-only probe was used for all four samples.",
            "No JumpPlus Discovery adapter, registry entry, Site Policy, Batch, or Catalog schema was changed.",
            "Manual rental detection requires row evidence plus structured purchase_info/status evidence when available.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("output/jumpplus_discovery_matrix"))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    comparison = build_comparison(args.input_dir)
    output = args.output or args.input_dir / "comparison.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Comparison saved to {output}")


if __name__ == "__main__":
    main()
