"""Contract tests for the Comic DAYS coefficient feasibility PoC."""

from __future__ import annotations

import pytest

from poc.comicdays_lossless_jpeg import runtime_plan


def _row(*, source_url: str = "blob:https://comic-days.com/test", width: int = 1125) -> dict:
    base = {
        "sequence": 10,
        "canvasWidth": width,
        "canvasHeight": 1600,
        "sourceId": 7,
        "sourceUrl": source_url,
        "source": {"id": 7, "url": source_url, "width": width, "height": 1600},
        "args": [0, 0, width, 1600, 0, 0, width, 1600],
    }
    mapping = []
    sequence = 11
    for y in range(0, 1600, 400):
        for x in range(0, 1120, 280):
            mapping.append(
                {
                    "sequence": sequence,
                    "canvasWidth": width,
                    "canvasHeight": 1600,
                    "sourceId": 7,
                    "sourceUrl": source_url,
                    "source": {"id": 7, "url": source_url, "width": width, "height": 1600},
                    "args": [x, y, 280, 400, x, y, 280, 400],
                }
            )
            sequence += 1
    return {"base": base, "mapping": mapping}


def test_runtime_plan_proves_comicdays_4x4_block_geometry_and_edge() -> None:
    plan = runtime_plan(_row())
    assert plan["tile_blocks"] == [35, 50]
    assert plan["tile_area_blocks"] == [140, 200]
    assert plan["coded_dimensions"] == [1128, 1600]
    assert plan["untiled_right_edge_pixels"] == 5
    assert plan["untiled_right_edge_blocks"] == [1]
    assert len(plan["mappings"]) == 16


def test_runtime_plan_uses_exact_source_identity_and_generation() -> None:
    row = _row()
    row["mapping"][0]["sourceUrl"] = "blob:https://comic-days.com/replaced"
    with pytest.raises(ValueError, match="identity replacement"):
        runtime_plan(row)

    row = _row()
    row["mapping"][0]["sequence"] = 9
    with pytest.raises(ValueError, match="precedes"):
        runtime_plan(row)


def test_runtime_plan_rejects_non_tile_geometry() -> None:
    row = _row()
    row["mapping"][0]["args"][2] = 272
    with pytest.raises(ValueError, match="tile geometry"):
        runtime_plan(row)


def test_runtime_plan_reports_seven_pixel_edge_for_observed_1127_source() -> None:
    plan = runtime_plan(_row(width=1127))
    assert plan["coded_dimensions"] == [1128, 1600]
    assert plan["untiled_right_edge_pixels"] == 7
    assert plan["untiled_right_edge_blocks"] == [1]
