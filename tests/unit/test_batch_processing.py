"""Batch Processing — unit tests.

Covers the original P11 DoD items (concurrent planning, rate-limit back-off,
progress callback, accept-mode split, Save All, sidecars) plus the two-mode
extension: per-image ``intent`` override (Mode B) and ``apply_plan_to_batch``
(Mode A — one approved plan recompiled per image).
"""

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


async def _run_batch_helper(
    records, accept_mode, on_progress=None, max_retries=0, intent="brighten"
):
    from vlm_photo_editor.pipeline.batch import run_batch

    return await run_batch(
        records,
        intent=intent,
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
        saved = _save_all_accepted(records, "same", out_dir, tmp_path / "recipes")

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
        saved = _save_all_accepted([record], "same", tmp_path, tmp_path / "recipes")

    assert saved == []
    mock_save.assert_not_called()


# ── PIP-S1 — provider exception text is sanitised before log/UI ──────────────


def test_safe_error_strips_url_and_truncates():
    from vlm_photo_editor.pipeline.batch import _safe_error

    exc = RuntimeError("call to https://api.example.com/v1?key=sk-secret failed")
    out = _safe_error(exc)
    assert "sk-secret" not in out
    assert "https://" not in out
    assert out.startswith("RuntimeError:")

    long = _safe_error(ValueError("x" * 500))
    assert len(long) < 250


# ── PIP-P1 — batch save writes a Recipe sidecar per output ──────────────────


def test_save_all_accepted_writes_recipe_sidecar(tmp_path):
    from vlm_photo_editor.app.components.batch_review import _save_all_accepted

    op_graph = OpGraph(
        ops=[Op(op_name=OpName.EXPOSURE, params={"ev": 0.5}, backend=Backend.PIL, step_id="s1")]
    )
    rec = BatchImageRecord(
        filename="photo.jpg",
        container=MagicMock(),
        edited_container=MagicMock(),
        op_graph=op_graph,
        status=ImageStatus.AUTO_EXECUTED,
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    recipes_dir = tmp_path / "recipes"

    with patch(
        "vlm_photo_editor.app.components.batch_review._save",
        MagicMock(return_value=out_dir / "photo_edited.jpg"),
    ):
        _save_all_accepted([rec], "same", out_dir, recipes_dir)

    sidecars = list(recipes_dir.glob("*.edit.json"))
    assert len(sidecars) == 1

    from vlm_photo_editor.recipe.store import RecipeStore

    loaded = RecipeStore.load(sidecars[0])
    assert loaded.op_graph.ops[0].step_id == "s1"


# ── PIP-P2 — batch re-plan forwards detected_subject ───────────────────────


def test_replan_record_forwards_detected_subject():
    import vlm_photo_editor.app.components.batch_review as br
    from vlm_photo_editor.schema.detection import DetectedSubject
    from vlm_photo_editor.schema.ops import BoundingBox
    from vlm_photo_editor.schema.plan import HumanPlan

    subject = DetectedSubject(
        bbox=BoundingBox(x=1, y=1, width=4, height=4),
        label="person",
        confidence=0.9,
        source="mediapipe",
    )
    rec = BatchImageRecord(
        filename="p.jpg",
        container=MagicMock(),
        plan=HumanPlan(steps=[]),
        detected_subject=subject,
        status=ImageStatus.NEEDS_REVIEW,
    )

    revise = MagicMock(return_value=HumanPlan(steps=[]))
    compile_ = MagicMock(return_value=MagicMock(plan=HumanPlan(steps=[]), op_graph=MagicMock()))

    with (
        patch("vlm_photo_editor.agents.planner.Planner.revise", revise),
        patch("vlm_photo_editor.planner.compiler.Compiler.compile", compile_),
        patch("vlm_photo_editor.background.providers.default_provider_available", lambda: False),
        patch.object(br.state, "get", lambda k: None),
        patch.object(br.st, "error", MagicMock()),
    ):
        br._replan_record(rec, "make it warmer")

    assert revise.call_args.kwargs["detected_subject"] is subject
    assert compile_.call_args.kwargs["detected_subject"] is subject


# ── Two-mode extension ───────────────────────────────────────────────────────
#
# Mode B: per-image `intent` override threaded through `_plan_single` / `run_batch`
#         and `_replan_record`.
# Mode A: `apply_plan_to_batch` — one approved HumanPlan recompiled per image,
#         each failure isolated, progress fired per record.


def _compile_result_with_graph(step_id: str):
    """A compile result whose op_graph is a real, distinct OpGraph (one LOW-risk op)."""
    result = MagicMock()
    result.plan = _fake_plan()
    result.op_graph = OpGraph(
        ops=[Op(op_name=OpName.EXPOSURE, params={"ev": 0.1}, backend=Backend.PIL, step_id=step_id)]
    )
    return result


def _patched_apply(compile_results):
    """Patch Compiler + Executor for an `apply_plan_to_batch` call.

    Returns (compiler_patch, executor_patch, mock_compiler_cls, mock_executor_cls).
    """
    mock_compiler_cls = MagicMock()
    mock_compiler_cls.return_value.compile.side_effect = list(compile_results)

    exec_result = MagicMock()
    exec_result.genai_ops = []
    mock_executor_cls = MagicMock()
    mock_executor_cls.return_value.apply.return_value = exec_result

    return (
        patch(_COMPILER_PATH, mock_compiler_cls),
        patch("vlm_photo_editor.ops.executor.Executor", mock_executor_cls),
        mock_compiler_cls,
        mock_executor_cls,
    )


def test_batch_record_intent_default():
    rec = BatchImageRecord(filename="a.jpg")
    assert rec.intent == ""
    roundtrip = BatchImageRecord.model_validate(rec.model_dump())
    assert roundtrip.intent == ""


@pytest.mark.parametrize("record_intent,expected", [("", "SHARED"), ("warmer", "warmer")])
def test_plan_single_prefers_record_intent(record_intent, expected):
    """`record.intent` overrides the batch-wide fallback; blank falls back to it."""
    records = [_make_record("img.jpg")]
    records[0].intent = record_intent

    planner_patch, compiler_patch = _patched_batch()
    with planner_patch as mock_planner, compiler_patch:
        anyio.run(_run_batch_helper, records, AcceptMode.MANUAL, None, 0, "SHARED")

    assert mock_planner.return_value.plan.call_args.args[1] == expected


def test_apply_plan_to_batch_recompiles_per_image():
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch

    subjects = ["subj-0", "subj-1", "subj-2"]
    records = []
    for i, s in enumerate(subjects):
        r = _make_record(f"img{i}.jpg")
        r.detected_subject = s
        records.append(r)

    results = [_compile_result_with_graph(f"s{i}") for i in range(3)]
    compiler_patch, executor_patch, mock_compiler, _ = _patched_apply(results)

    with compiler_patch, executor_patch:
        out = apply_plan_to_batch(records, _fake_plan(), "full")

    assert out is records
    calls = mock_compiler.return_value.compile.call_args_list
    assert len(calls) == 3
    for i, call in enumerate(calls):
        assert call.kwargs["detected_subject"] == subjects[i]
    assert all(r.status == ImageStatus.AUTO_EXECUTED for r in records)
    for r, res in zip(records, results):
        assert r.op_graph is res.op_graph
    assert len({id(r.op_graph) for r in records}) == 3


def test_apply_plan_to_batch_progress_per_image():
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch

    records = [_make_record(f"img{i}.jpg") for i in range(3)]
    results = [_compile_result_with_graph(f"s{i}") for i in range(3)]
    compiler_patch, executor_patch, _, _ = _patched_apply(results)
    seen: list[str] = []

    with compiler_patch, executor_patch:
        apply_plan_to_batch(records, _fake_plan(), "full", seen.append)

    assert len(seen) == 3
    assert set(seen) == {r.image_id for r in records}


def test_apply_plan_to_batch_crop_oob_isolated():
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch

    records = [_make_record(f"img{i}.jpg") for i in range(3)]
    results = [_compile_result_with_graph(f"s{i}") for i in range(3)]
    compiler_patch, executor_patch, _, _ = _patched_apply(results)

    calls = [0]

    def fake_validate(*_a, **_k):
        calls[0] += 1
        if calls[0] == 2:
            raise ValueError("crop out of bounds")

    seen: list[str] = []
    with (
        compiler_patch,
        executor_patch,
        patch("vlm_photo_editor.ops.validator.validate_crop_bounds", fake_validate),
    ):
        apply_plan_to_batch(records, _fake_plan(), "full", seen.append)

    assert records[0].status == ImageStatus.AUTO_EXECUTED
    assert records[1].status == ImageStatus.FAILED
    assert records[1].error is not None
    assert records[2].status == ImageStatus.AUTO_EXECUTED
    assert len(seen) == 3  # loop not aborted; progress fired for every record


def test_apply_plan_to_batch_executor_error_isolated():
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch

    records = [_make_record(f"img{i}.jpg") for i in range(3)]
    results = [_compile_result_with_graph(f"s{i}") for i in range(3)]

    mock_compiler_cls = MagicMock()
    mock_compiler_cls.return_value.compile.side_effect = results

    apply_calls = [0]

    def flaky_apply(*_a, **_k):
        apply_calls[0] += 1
        if apply_calls[0] == 2:
            raise RuntimeError("executor boom")
        res = MagicMock()
        res.genai_ops = []
        return res

    mock_executor_cls = MagicMock()
    mock_executor_cls.return_value.apply.side_effect = flaky_apply

    with (
        patch(_COMPILER_PATH, mock_compiler_cls),
        patch("vlm_photo_editor.ops.executor.Executor", mock_executor_cls),
    ):
        apply_plan_to_batch(records, _fake_plan(), "full")

    assert records[0].status == ImageStatus.AUTO_EXECUTED
    assert records[1].status == ImageStatus.FAILED
    assert records[1].error is not None
    assert records[2].status == ImageStatus.AUTO_EXECUTED


def test_apply_plan_to_batch_sets_op_graph_for_sidecar(tmp_path):
    from vlm_photo_editor.app.components.batch_review import _save_all_accepted
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch
    from vlm_photo_editor.recipe.store import RecipeStore

    records = [_make_record(f"img{i}.jpg") for i in range(2)]
    results = [_compile_result_with_graph(f"step-{i}") for i in range(2)]
    compiler_patch, executor_patch, _, _ = _patched_apply(results)

    with compiler_patch, executor_patch:
        apply_plan_to_batch(records, _fake_plan(), "full")

    assert records[0].op_graph.ops[0].step_id == "step-0"
    assert records[1].op_graph.ops[0].step_id == "step-1"

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    recipes_dir = tmp_path / "recipes"
    saved_paths = [out_dir / f"img{i}_edited.jpg" for i in range(2)]

    with patch(
        "vlm_photo_editor.app.components.batch_review._save",
        MagicMock(side_effect=saved_paths),
    ):
        _save_all_accepted(records, "same", out_dir, recipes_dir)

    sidecars = sorted(recipes_dir.glob("*.edit.json"))
    assert len(sidecars) == 2
    step_ids = {RecipeStore.load(s).op_graph.ops[0].step_id for s in sidecars}
    assert step_ids == {"step-0", "step-1"}


def test_apply_plan_to_batch_is_sync():
    from vlm_photo_editor.pipeline.batch import apply_plan_to_batch

    records = [_make_record("img.jpg")]
    compiler_patch, executor_patch, _, _ = _patched_apply([_compile_result_with_graph("s0")])

    with compiler_patch, executor_patch:
        result = apply_plan_to_batch(records, _fake_plan(), "full")  # no anyio.run

    assert result is records
    assert records[0].status == ImageStatus.AUTO_EXECUTED


def test_replan_record_prefers_record_intent():
    import vlm_photo_editor.app.components.batch_review as br

    rec = BatchImageRecord(
        filename="p.jpg",
        container=MagicMock(),
        plan=None,  # fallback branch -> anyio.run(run_batch, ...)
        intent="foo",
        status=ImageStatus.FAILED,
    )

    fake_anyio_run = MagicMock()
    with (
        patch("vlm_photo_editor.pipeline.batch.run_batch", MagicMock()),
        patch.object(br.state, "get", lambda k: None),
        patch.object(br.st, "error", MagicMock()),
        patch("anyio.run", fake_anyio_run),
    ):
        br._replan_record(rec, "make it warmer")

    # anyio.run(run_batch, [record], intent, prefs, mode, None, accept_mode, 3, None)
    assert fake_anyio_run.call_args.args[2] == "foo"
