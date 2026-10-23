"""Resource event truth and cooperative stops, without any site or browser."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from screenshot_crawler import cli
from screenshot_crawler.batch.models import BatchCandidate


@pytest.mark.parametrize(
    ("consumed", "cancel_during_debit"),
    [(False, False), (None, False), (True, True), (True, False)],
    ids=["known-not-consumed", "unknown-consumption", "stop-during-debit", "confirmed"],
)
async def test_grant_events_preserve_observation_and_stop_before_next_attempt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], consumed: bool | None,
    cancel_during_debit: bool,
) -> None:
    state = {"cancel": False}
    operations = []
    events = []
    confirmed = []

    class Session:
        async def new_page(self):
            operations.append("open")
            return object()

        async def close_page(self, page):
            operations.append("close")

    class Executor:
        def grant_only_skip_reason(self, candidate):
            return None

        async def execute_grant_only_candidate(self, page, candidate, **kwargs):
            operations.append(f"debit:{candidate.item_id}")
            state["cancel"] = cancel_during_debit
            await asyncio.sleep(0)
            operations.append(f"observed:{candidate.item_id}")
            return SimpleNamespace(resource="synthetic_resource", resource_consumed=consumed)

    args = SimpleNamespace(
        site="synthetic", output_root=tmp_path / "batch", max_pages=10,
        max_same_content=2, keep_open=False, cancel_check=lambda: state["cancel"],
        event_sink=lambda name, **fields: events.append((name, fields)),
    )
    candidates = [
        BatchCandidate(
            item_id=item_id, source_id=item_id, target_id=item_id, site="synthetic",
            backend="web", target_key="default", locator="https://example.invalid",
            access_strategy="quota", consumes_quota=True,
            quota_resource="synthetic_resource", quota_commit_mode="after_observed_consumption",
            discovery_key="selected-key",
        )
        for item_id in (1, 2)
    ]

    async def run():
        return await cli._execute_batch_candidates(
            args, Session(), Executor(), candidates, phase="synthetic",
            inter_candidate_delay_ms=0, grant_only=True, confirmed_grants=confirmed,
        )

    if consumed is not True:
        with pytest.raises(cli.BatchExecutionError):
            await run()
        assert not confirmed
        assert not any(name == "grant_confirmed" for name, _ in events)
        assert any(name == "grant_unknown" and fields["resource_consumed"] is consumed
                   for name, fields in events)
    elif cancel_during_debit:
        with pytest.raises(cli.BatchInterruptedError, match="cooperative stop"):
            await run()
        assert confirmed == [candidates[0]]
        assert any(name == "candidate_finished" and fields["result"] == "succeeded"
                   for name, fields in events)
    else:
        assert await run() == (2, True)
        assert confirmed == candidates

    expected = 2 if consumed is True and not cancel_during_debit else 1
    assert operations == [value for item_id in range(1, expected + 1)
                          for value in ("open", f"debit:{item_id}", f"observed:{item_id}", "close")]
    grants = [fields for name, fields in events if name == "grant_confirmed"]
    assert len(grants) == (expected if consumed is True else 0)
    assert all(fields["resource_consumed"] is True for fields in grants)
    assert capsys.readouterr().out.count("grant confirmed:") == len(grants)
    assert all(fields.get("key") == "selected-key" for name, fields in events
               if name in {"candidate_started", "candidate_finished", "grant_confirmed"})
