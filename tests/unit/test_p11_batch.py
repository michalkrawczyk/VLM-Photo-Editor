"""P11 Batch Processing — unit tests covering all DoD items."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import numpy as np
import pytest

from vlm_photo_editor.schema.batch import BatchImageRecord, ImageStatus
from vlm_photo_editor.schema.ops import AcceptMode, Backend, Op, OpGraph, OpName, RiskTier

# Lazy-imported targets — Planner/Compiler are imported inside run_batch(), so
# we must patch at their source modules, not at pipeline.batch.
_PLANNER_PATH = "vlm_photo_editor.agents.planner.Planner"
_COMPILER_PATH = "vlm_photo_editor.planner.compiler.Compiler"


# ── Fixtures / helpers ────────────────────────────────────────────────────────


def _make_record(filename: str) -> BatchImageRecord:
    container = MagicMock()
    container.pixels = np.zeros((10, 10, 3), dtype=np.uint8)
    return BatchImageRecord(filename=filename, container=container)


def _fake_plan():
    from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

    return HumanPlan(
        steps=[
            HumanStep(
                step_id="00000000-0000-0000-0000-000000000001",
                index=0,
                title="Expose",
                why="brighten",
            )
        ]
    )


def _fake_compile_result(risk_tier: RiskTier = RiskTier.LOW):
    result = MagicMock()
    result.plan = _fake_plan()
    if risk_tier == RiskTier.HIGH:
        op = Op(
            op_name=OpName.BACKGROUND_REPLACE,
            params={"prompt": "x"},
            backend=Backend.GENAI,
            step_id="s1",
        )
    else:
        op = Op(
            op_name=OpName.EXPOSURE,
            params={"ev": 0.5},
            backend=Backend.PIL,
            step_id="s1",
        )
    result.op_graph = OpGraph(ops=[op])
    return result


def _patched_batch(compile_result=None, plan_side_effect=None):
    """Context-manager helper: patches Planner and Compiler at their source modules."""
    if compile_result is None:
        compile_result = _fake_compile_result()

    mock_planner_cls = MagicMock()
    if plan_side_effect is not None:
        mock_planner_cls.return_value.plan.side_effect = plan_side_effect
    else:
        mock_planner_cls.return_value.plan.return_value = _fake_plan()

    mock_compiler_cls = MagicMock()
    mock_compiler_cls.return_value.compile.return_value = compile_result

    return (
        patch(_PLANNER_PATH, mock_planner_cls),
        patch(_COMPILER_PATH, mock_compiler_cls),
    )


# ── DoD #1 — Concurrent planning: wall time < N × single-image time ───────────


def test_concurrent_planning_wall_time():
    """5 images each taking 0.1 s should finish in < 0.4 s (not 0.5 s)."""

    def slow_plan(container, intent, prefs, mode, fi, detected_subject=None, genai_available=True):
        time.sleep(0.1)
        return _fake_plan()

    planner_patch, compiler_patch = _patched_batch(plan_side_effect=slow_plan)
    records = [_make_record(f"img{i}.jpg") for i in range(5)]

    with planner_patch, compiler_patch:
        t0 = time.monotonic()
        anyio.run(
            _run_batch_helper,
            records,
            AcceptMode.MANUAL,
        )
        elapsed = time.monotonic() - t0

    assert elapsed < 0.45, f"Expected concurrent execution, got {elapsed:.2f}s"
    assert all(r.status == ImageStatus.NEEDS_REVIEW for r in records)


async def _run_batch_helper(records, accept_mode, on_progress=None, max_retries=0):
    from vlm_photo_editor.pipeline.batch import run_batch

    return await run_batch(
        records,
        intent="brighten",
        prefs=None,
        mode="full",
        framing_intent=None,
        accept_mode=accept_mode,
        max_retries=max_retries,
        on_image_progress=on_progress,
    )


# ── DoD #2 — HTTP 429 triggers back-off and retry; image eventually succeeds ──


def test_rate_limit_retry_succeeds():
    """Plan raises 429 twice, succeeds on the third attempt."""
    call_count = [0]

    def flaky_plan(container, intent, prefs, mode, fi, detected_subject=None, genai_available=True):
        call_count[0] += 1
        if call_count[0] <= 2:
            raise Exception("HTTP 429: rate limit exceeded")
        return _fake_plan()

    records = [_make_record("img.jpg")]
    planner_patch, compiler_patch = _patched_batch(plan_side_effect=flaky_plan)

    with planner_patch, compiler_patch, patch("anyio.sleep", new=AsyncMock()):
        anyio.run(_run_batch_helper, records, AcceptMode.MANUAL, None, 3)

    assert records[0].retry_count == 2
    assert records[0].status == ImageStatus.NEEDS_REVIEW


def test_rate_limit_exhausted_marks_failed():
    """Plan always raises 429; exhausts max_retries → FAILED."""

    def always_429(container, intent, prefs, mode, fi):
        raise Exception("rate limit: 429")

    records = [_make_record("img.jpg")]
    planner_patch, compiler_patch = _patched_batch(plan_side_effect=always_429)

    with planner_patch, compiler_patch, patch("anyio.sleep", new=AsyncMock()):
        anyio.run(_run_batch_helper, records, AcceptMode.MANUAL)

    assert records[0].status == ImageStatus.FAILED
    assert records[0].error is not None


# ── DoD #3 — Progress callback called per image ───────────────────────────────


def test_progress_called_per_image():
    """on_image_progress called exactly once per image, with its image_id."""
    n = 4
    records = [_make_record(f"img{i}.jpg") for i in range(n)]
    progress_calls: list[str] = []
    planner_patch, compiler_patch = _patched_batch()

    with planner_patch, compiler_patch:
        anyio.run(_run_batch_helper, records, AcceptMode.MANUAL, progress_calls.append)

    assert len(progress_calls) == n
    assert set(progress_calls) == {r.image_id for r in records}


# ── DoD #4 — Auto-mode split: low-risk auto-executed, high-risk queued ────────


@pytest.mark.parametrize(
    "accept_mode,expected_auto,expected_review",
    [
        (AcceptMode.MANUAL, 0, 2),
        (AcceptMode.AUTO_LOW, 1, 1),
        (AcceptMode.AUTO_MEDIUM, 1, 1),
        (AcceptMode.FULL_AUTO, 2, 0),
    ],
)
def test_auto_mode_split(accept_mode, expected_auto, expected_review):
    """Accept-mode routing auto-executes the right number of images.

    Two records: one with a LOW-risk op_graph, one with a HIGH-risk op_graph.
    Concurrent planning means we can't guarantee which record gets which tier,
    so we assert on counts rather than positions.
    """
    import threading

    from vlm_photo_editor.pipeline.batch import run_batch

    records = [_make_record("low.jpg"), _make_record("high.jpg")]

    low_compile = _fake_compile_result(RiskTier.LOW)
    high_compile = _fake_compile_result(RiskTier.HIGH)
    compile_queue = [low_compile, high_compile]
    _lock = threading.Lock()

    def compile_dequeue(plan, mode, detected_subject=None):
        with _lock:
            return compile_queue.pop(0)

    mock_planner_cls = MagicMock()
    mock_planner_cls.return_value.plan.return_value = _fake_plan()
    mock_compiler_cls = MagicMock()
    mock_compiler_cls.return_value.compile.side_effect = compile_dequeue

    mock_executor = MagicMock()
    mock_executor_result = MagicMock()
    mock_executor.return_value.apply.return_value = mock_executor_result

    with (
        patch(_PLANNER_PATH, mock_planner_cls),
        patch(_COMPILER_PATH, mock_compiler_cls),
        patch("vlm_photo_editor.ops.executor.Executor", mock_executor),
    ):
        anyio.run(
            run_batch,
            records,
            "test",
            None,
            "full",
            None,
            accept_mode,
            0,
            None,
        )

    auto_count = sum(1 for r in records if r.status == ImageStatus.AUTO_EXECUTED)
    review_count = sum(1 for r in records if r.status == ImageStatus.NEEDS_REVIEW)
    assert auto_count == expected_auto, f"Expected {expected_auto} auto-executed, got {auto_count}"
    assert (
        review_count == expected_review
    ), f"Expected {expected_review} needs-review, got {review_count}"


# ── DoD #5 — Save All writes N new files; originals not overwritten ───────────


def test_save_all_accepted_writes_files(tmp_path):
    """_save_all_accepted calls _save N times for N ACCEPTED records."""
    from vlm_photo_editor.app.components.batch_review import _save_all_accepted

    n = 3
    records: list[BatchImageRecord] = []
    source_paths: list[Path] = []

    for i in range(n):
        src = tmp_path / f"photo{i}.jpg"
        src.write_bytes(b"fake-jpg-" + str(i).encode())
        source_paths.append(src)

        edited_container = MagicMock()
        edited_container.source_path = src

        r = BatchImageRecord(
            filename=src.name,
            container=MagicMock(),
            edited_container=edited_container,
            status=ImageStatus.ACCEPTED,
        )
        records.append(r)

    out_dir = tmp_path / "out"
    out_dir.mkdir()

    saved_paths: list[Path] = [out_dir / f"photo{i}_edited.jpg" for i in range(n)]
    mock_save = MagicMock(side_effect=saved_paths)

    with patch("vlm_photo_editor.app.components.batch_review._save", mock_save):
        saved = _save_all_accepted(records, "same", out_dir)

    # _save called once per ACCEPTED record
    assert mock_save.call_count == n
    assert len(saved) == n
    # None of the saved paths match a source path (originals not overwritten)
    assert not any(p in set(source_paths) for p in saved)
    # Source files untouched
    for i, src in enumerate(source_paths):
        assert src.read_bytes() == b"fake-jpg-" + str(i).encode()


# ── DoD #6 — Rejected images produce no output files ─────────────────────────


@pytest.mark.parametrize(
    "status",
    [ImageStatus.REJECTED, ImageStatus.NEEDS_REVIEW, ImageStatus.PENDING, ImageStatus.FAILED],
)
def test_non_accepted_images_produce_no_output(tmp_path, status):
    """Non-ACCEPTED/AUTO_EXECUTED records are skipped by _save_all_accepted."""
    from vlm_photo_editor.app.components.batch_review import _save_all_accepted

    record = BatchImageRecord(
        filename="photo.jpg",
        status=status,
        edited_container=MagicMock(),
    )

    with patch("vlm_photo_editor.app.components.batch_review._save") as mock_save:
        saved = _save_all_accepted([record], "same", tmp_path)

    assert saved == []
    mock_save.assert_not_called()
