from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = WORKSPACE_ROOT / "skills" / "workflow"
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from fusion_flow.token_usage import TokenCount, TokenUsageCollector, TokenUsageStore  # noqa: E402


def test_collector_merges_response_retries_and_preserves_unknown_usage() -> None:
    collector = TokenUsageCollector()
    collector.record(
        step_id="draft",
        executor_id="writer",
        executor_kind="Agent",
        attempt=1,
        iteration_index=None,
        usage=TokenCount(model_calls=1, input_tokens=100, output_tokens=10),
    )
    collector.record(
        step_id="draft",
        executor_id="writer",
        executor_kind="Agent",
        attempt=1,
        iteration_index=None,
        usage=TokenCount(model_calls=1, input_tokens=20, output_tokens=4),
    )
    collector.record(
        step_id="draft",
        executor_id="writer",
        executor_kind="Agent",
        attempt=2,
        iteration_index=None,
        usage=TokenCount(model_calls=1, input_tokens=None, output_tokens=None),
    )

    step = collector.snapshot()[0]
    assert step.attempts[0].usage == TokenCount(model_calls=2, input_tokens=120, output_tokens=14)
    assert step.usage.model_calls == 3
    assert step.usage.input_tokens is None
    assert step.usage.output_tokens is None
    assert not step.usage.complete
    assert not collector.totals.complete


def test_collector_keeps_foreach_iterations_separate() -> None:
    collector = TokenUsageCollector()
    for iteration_index, input_tokens in enumerate((30, 40)):
        collector.record(
            step_id="score_each",
            executor_id="scorer",
            executor_kind="Agent",
            attempt=1,
            iteration_index=iteration_index,
            usage=TokenCount(model_calls=1, input_tokens=input_tokens, output_tokens=5),
        )

    step = collector.snapshot()[0]
    assert [(item.iteration_index, item.attempt) for item in step.attempts] == [(0, 1), (1, 1)]
    assert step.usage == TokenCount(model_calls=2, input_tokens=70, output_tokens=10)


def test_collector_aggregates_cache_breakdown_independently() -> None:
    collector = TokenUsageCollector()
    for attempt, input_tokens, cached_tokens, creation_tokens in (
        (1, 100, 70, 10),
        (2, 50, 20, 5),
    ):
        collector.record(
            step_id="draft",
            executor_id="writer",
            executor_kind="Agent",
            attempt=attempt,
            iteration_index=None,
            usage=TokenCount(
                model_calls=1,
                input_tokens=input_tokens,
                output_tokens=5,
                cached_input_tokens=cached_tokens,
                cache_creation_input_tokens=creation_tokens,
            ),
        )

    usage = collector.snapshot()[0].usage
    assert usage.cached_input_tokens == 90
    assert usage.cache_creation_input_tokens == 15
    assert usage.uncached_input_tokens == 45
    assert usage.cache_hit_rate == pytest.approx(0.6)
    assert usage.cache_read_complete
    assert usage.cache_creation_complete


def test_collector_preserves_unknown_cache_creation_without_losing_cache_reads() -> None:
    collector = TokenUsageCollector()
    collector.record(
        step_id="draft",
        executor_id="writer",
        executor_kind="Agent",
        attempt=1,
        iteration_index=None,
        usage=TokenCount(
            model_calls=1,
            input_tokens=100,
            output_tokens=5,
            cached_input_tokens=70,
        ),
    )

    usage = collector.snapshot()[0].usage
    assert usage.cached_input_tokens == 70
    assert usage.cache_creation_input_tokens is None
    assert usage.uncached_input_tokens is None
    assert usage.cache_hit_rate == pytest.approx(0.7)
    assert usage.cache_read_complete
    assert not usage.cache_creation_complete


def test_token_count_preserves_reported_zero_cache_usage() -> None:
    usage = TokenCount(
        model_calls=1,
        input_tokens=100,
        output_tokens=5,
        cached_input_tokens=0,
        cache_creation_input_tokens=0,
    )

    assert usage.cached_input_tokens == 0
    assert usage.cache_creation_input_tokens == 0
    assert usage.uncached_input_tokens == 100
    assert usage.cache_hit_rate == 0.0
    assert usage.cache_read_complete
    assert usage.cache_creation_complete


def test_token_count_rejects_cache_breakdown_greater_than_input() -> None:
    with pytest.raises(ValueError, match="cache token breakdown"):
        TokenCount(
            model_calls=1,
            input_tokens=100,
            output_tokens=5,
            cached_input_tokens=80,
            cache_creation_input_tokens=30,
        )


@pytest.mark.anyio
async def test_store_persists_resumes_and_finalizes(tmp_path: Path) -> None:
    run_dir = anyio.Path(tmp_path / "run-1")
    store = await TokenUsageStore.open(
        run_dir,
        run_id="run-1",
        workflow_id="wf-1",
        flow_path="flows/example.workflow",
    )
    store.collector.record(
        step_id="prepare",
        executor_id="preparer",
        executor_kind="Human",
        attempt=1,
        iteration_index=None,
        usage=TokenCount(
            model_calls=1,
            input_tokens=50,
            output_tokens=8,
            cached_input_tokens=30,
            cache_creation_input_tokens=5,
        ),
    )
    await store.persist()

    running = json.loads(await (run_dir / "token-usage.json").read_text(encoding="utf-8"))
    assert running["status"] == "running"
    assert running["version"] == 2
    assert running["complete"] is True
    assert running["totals"] == {
        "cache_creation_complete": True,
        "cache_creation_input_tokens": 5,
        "cache_hit_rate": 0.6,
        "cache_read_complete": True,
        "cached_input_tokens": 30,
        "complete": True,
        "input_tokens": 50,
        "model_calls": 1,
        "output_tokens": 8,
        "total_tokens": 58,
        "uncached_input_tokens": 15,
    }

    resumed = await TokenUsageStore.open(
        run_dir,
        run_id="run-1",
        workflow_id="wf-1",
        flow_path="flows/example.workflow",
    )
    resumed.collector.record(
        step_id="finish",
        executor_id="closer",
        executor_kind="Program",
        attempt=1,
        iteration_index=None,
        usage=TokenCount(
            model_calls=2,
            input_tokens=70,
            output_tokens=12,
            cached_input_tokens=40,
            cache_creation_input_tokens=10,
        ),
    )
    await resumed.finalize(status="completed", error_type=None)

    completed = json.loads(await (run_dir / "token-usage.json").read_text(encoding="utf-8"))
    assert completed["status"] == "completed"
    assert completed["totals"]["model_calls"] == 3
    assert completed["totals"]["input_tokens"] == 120
    assert completed["totals"]["output_tokens"] == 20
    assert completed["totals"]["cached_input_tokens"] == 70
    assert completed["totals"]["cache_creation_input_tokens"] == 15
    assert completed["totals"]["uncached_input_tokens"] == 35
    assert [step["step_id"] for step in completed["steps"]] == ["finish", "prepare"]


@pytest.mark.anyio
async def test_store_resumes_version_one_with_unknown_cache_details(tmp_path: Path) -> None:
    run_dir = anyio.Path(tmp_path / "legacy-run")
    await run_dir.mkdir(parents=True)
    legacy = {
        "version": 1,
        "run_id": "legacy-run",
        "workflow_id": "wf-1",
        "flow_path": "flows/example.workflow",
        "status": "running",
        "error_type": None,
        "complete": True,
        "totals": {
            "model_calls": 1,
            "input_tokens": 50,
            "output_tokens": 8,
            "total_tokens": 58,
            "complete": True,
        },
        "steps": [
            {
                "step_id": "prepare",
                "executor_id": "preparer",
                "executor_kind": "Agent",
                "model_calls": 1,
                "input_tokens": 50,
                "output_tokens": 8,
                "total_tokens": 58,
                "complete": True,
                "attempts": [
                    {
                        "attempt": 1,
                        "iteration_index": None,
                        "model_calls": 1,
                        "input_tokens": 50,
                        "output_tokens": 8,
                        "total_tokens": 58,
                        "complete": True,
                    }
                ],
            }
        ],
    }
    await (run_dir / "token-usage.json").write_text(json.dumps(legacy), encoding="utf-8")

    store = await TokenUsageStore.open(
        run_dir,
        run_id="legacy-run",
        workflow_id="wf-1",
        flow_path="flows/example.workflow",
    )
    usage = store.collector.snapshot()[0].usage
    assert usage.input_tokens == 50
    assert usage.cached_input_tokens is None
    assert usage.cache_creation_input_tokens is None

    await store.persist()
    upgraded = json.loads(await (run_dir / "token-usage.json").read_text(encoding="utf-8"))
    assert upgraded["version"] == 2
    assert upgraded["totals"]["cached_input_tokens"] is None
    assert upgraded["totals"]["cache_creation_input_tokens"] is None
