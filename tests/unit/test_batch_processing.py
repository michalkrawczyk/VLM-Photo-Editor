"""Batch Processing — unit tests.

Covers the original P11 DoD items (concurrent planning, rate-limit back-off,
progress callback, accept-mode split, Save All, sidecars) plus the two-mode
extension: per-image ``intent`` override (Mode B) and ``apply_plan_to_batch``
(Mode A — one approved plan recompiled per image).
"""

from __future__ import annotations

import time
import uuid
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

    report = object()  # opaque sentinel; compute_report is stubbed (the container is a mock)

    with (
        patch("vlm_photo_editor.agents.planner.Planner.revise", revise),
        patch("vlm_photo_editor.planner.compiler.Compiler.compile", compile_),
        patch("vlm_photo_editor.background.providers.default_provider_available", lambda: False),
        patch("vlm_photo_editor.analysis.compute_report", lambda container: report),
        patch.object(br.state, "get", lambda k: None),
        patch.object(br.st, "error", MagicMock()),
    ):
        br._replan_record(rec, "make it warmer")

    assert revise.call_args.kwargs["detected_subject"] is subject
    assert revise.call_args.kwargs["image_report"] is report
    assert compile_.call_args.kwargs["detected_subject"] is subject


@pytest.mark.parametrize(
    "repairs_needed,expected_status",
    [(1, ImageStatus.NEEDS_REVIEW), (99, ImageStatus.FAILED)],
    ids=["crop_repaired", "budget_exhausted"],
)
def test_plan_single_repairs_out_of_bounds_crop(repairs_needed, expected_status):
    """Batch planning validates crops against each image and revises within the budget."""
    from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

    def crop_plan(right: int) -> HumanPlan:
        return HumanPlan(
            steps=[
                HumanStep(
                    step_id="00000000-0000-0000-0000-000000000001",
                    index=0,
                    title="Crop",
                    why="tighten",
                    op_names=["crop"],
                    op_params=[{"left": 0, "top": 0, "right": right, "bottom": 50}],
                )
            ]
        )

    record = _make_record("img.jpg")
    record.container.width, record.container.height = 100, 80

    mock_planner_cls = MagicMock()
    mock_planner_cls.return_value.plan.return_value = crop_plan(200)
    revisions = iter(range(repairs_needed))
    mock_planner_cls.return_value.revise.side_effect = lambda *a, **k: crop_plan(
        80 if next(revisions, None) is None else 200
    )

    with patch(_PLANNER_PATH, mock_planner_cls):
        anyio.run(_run_batch_helper, [record], AcceptMode.MANUAL)

    assert record.status == expected_status
    assert mock_planner_cls.return_value.revise.call_count >= 1
    if expected_status == ImageStatus.FAILED:
        assert "right=200 > image width 100" in record.error


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


# ── Batch results viewer + framing/intent forwarding ──────────────────────────


def _rec(status: ImageStatus, *, edited: bool = False) -> BatchImageRecord:
    return BatchImageRecord(
        filename=f"{status.value}.jpg",
        container=MagicMock(),
        edited_container=MagicMock(pixels="after") if edited else None,
        status=status,
    )


@pytest.mark.parametrize(
    "idx, n, expected",
    [(-3, 4, 0), (0, 4, 0), (2, 4, 2), (9, 4, 3), (0, 1, 0)],
)
def test_viewer_clamp_index(idx, n, expected):
    import vlm_photo_editor.app.components.batch_review as br

    assert br._clamp_index(idx, n) == expected


@pytest.mark.parametrize(
    "statuses, idx, expected",
    [
        # next pending after idx
        ([ImageStatus.NEEDS_REVIEW, ImageStatus.ACCEPTED, ImageStatus.NEEDS_REVIEW], 0, 2),
        # wraps around to an earlier pending record
        ([ImageStatus.NEEDS_REVIEW, ImageStatus.ACCEPTED, ImageStatus.ACCEPTED], 2, 0),
        # nothing pending: stay put
        ([ImageStatus.ACCEPTED, ImageStatus.AUTO_EXECUTED], 1, 1),
    ],
)
def test_viewer_next_review_index(statuses, idx, expected):
    import vlm_photo_editor.app.components.batch_review as br

    records = [_rec(s) for s in statuses]
    assert br._next_review_index(records, idx) == expected


def test_viewer_after_pixels_only_when_executed():
    import vlm_photo_editor.app.components.batch_review as br

    assert br._after_pixels(_rec(ImageStatus.NEEDS_REVIEW)) is None
    assert br._after_pixels(_rec(ImageStatus.AUTO_EXECUTED, edited=True)) == "after"


def test_replan_record_forwards_framing_and_original_intent():
    import vlm_photo_editor.app.components.batch_review as br
    from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
    from vlm_photo_editor.schema.plan import HumanPlan

    rec = BatchImageRecord(
        filename="p.jpg",
        container=MagicMock(),
        plan=HumanPlan(steps=[]),
        intent="portrait headroom",
        status=ImageStatus.NEEDS_REVIEW,
    )
    fi = FramingIntent(mode=FramingMode.PORTRAIT_HEADROOM, focus_instruction="f", frame_ratio="4:5")
    revise = MagicMock(return_value=HumanPlan(steps=[]))
    compile_ = MagicMock(return_value=MagicMock(plan=HumanPlan(steps=[]), op_graph=MagicMock()))

    with (
        patch("vlm_photo_editor.agents.planner.Planner.revise", revise),
        patch("vlm_photo_editor.planner.compiler.Compiler.compile", compile_),
        patch("vlm_photo_editor.background.providers.default_provider_available", lambda: False),
        patch("vlm_photo_editor.analysis.compute_report", lambda container: object()),
        patch.object(br, "current_framing_intent", lambda: fi),
        patch.object(br.state, "get", lambda k: None),
        patch.object(br.st, "error", MagicMock()),
    ):
        br._replan_record(rec, "crop face only")

    assert revise.call_args.args[5] is fi
    assert revise.call_args.kwargs["original_intent"] == "portrait headroom"


# ── Batch preview (top of panel) ──────────────────────────────────────────────


def _preview_app(kind: str) -> None:
    """AppTest script: render_preview over fake uploads (pre-run) or records (post-run)."""
    import io
    from types import SimpleNamespace as NS

    import numpy as np
    from PIL import Image

    from vlm_photo_editor.app import state
    from vlm_photo_editor.app.components import batch_review
    from vlm_photo_editor.schema.batch import BatchImageRecord, ImageStatus

    state.init_state()

    def jpg(color):
        buf = io.BytesIO()
        Image.new("RGB", (4000, 3000), color).save(buf, "JPEG")
        return buf.getvalue()

    files = [
        NS(name="a.jpg", size=1, getvalue=lambda b=jpg("red"): b),
        NS(name="b.jpg", size=2, getvalue=lambda b=jpg("blue"): b),
        NS(name="raw.nef", size=3, getvalue=lambda: b"not decodable"),
    ]
    records = None
    if kind == "post":
        px = np.zeros((20, 20, 3), dtype=np.uint8)
        c = NS(pixels=px, width=20, height=20)
        records = [
            BatchImageRecord(
                filename="a.jpg", container=c, edited_container=c, status=ImageStatus.AUTO_EXECUTED
            ),
            BatchImageRecord(filename="b.jpg", container=c, status=ImageStatus.NEEDS_REVIEW),
            BatchImageRecord(filename="raw.nef", container=c, status=ImageStatus.FAILED),
        ]
    batch_review.render_preview(files, records)


def _captions(at) -> list[str]:
    return [c.value for c in at.caption]


@pytest.mark.parametrize(
    "kind, first_after, second_status",
    [("pre", "After (pending execution)", None), ("post", "After", "needs review")],
)
def test_render_preview_walks_all_images(kind, first_after, second_status):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_function(_preview_app, args=(kind,)).run()
    assert not at.exception
    assert "Before" in _captions(at) and first_after in _captions(at)
    assert any("Image 1 of 3: **a.jpg**" in c for c in _captions(at))
    assert at.button(key="batch_nav_prev").disabled

    at.button(key="batch_nav_next").click().run()
    assert any("Image 2 of 3: **b.jpg**" in c for c in _captions(at))
    if second_status:
        assert any(second_status in c for c in _captions(at))
    if kind == "post":  # b.jpg was never executed
        assert "After (pending execution)" in _captions(at)

    at.button(key="batch_nav_next").click().run()
    assert at.button(key="batch_nav_next").disabled
    if kind == "pre":  # RAW has no pre-run preview
        assert any("RAW preview available after processing" in c for c in _captions(at))

    at.button(key="batch_nav_prev").click().run()
    assert any("Image 2 of 3" in c for c in _captions(at))


def test_original_pixels_caps_size_and_caches():
    import io
    from types import SimpleNamespace as NS

    from PIL import Image

    import vlm_photo_editor.app.components.batch_review as br

    buf = io.BytesIO()
    Image.new("RGB", (4000, 3000), "red").save(buf, "JPEG")
    calls = []

    def getvalue():
        calls.append(1)
        return buf.getvalue()

    cache: dict = {}
    with patch.object(br.st, "session_state", {br._PREVIEW_CACHE_KEY: cache}):
        f = NS(name="a.jpg", size=1, getvalue=getvalue)
        px = br._original_pixels(f)
        assert max(px.shape[:2]) == br._PREVIEW_MAX_EDGE
        br._original_pixels(f)
        assert len(calls) == 1  # second call served from cache

        assert br._original_pixels(NS(name="x.NEF", size=2, getvalue=getvalue)) is None
        assert br._original_pixels(NS(name="bad.jpg", size=3, getvalue=lambda: b"junk")) is None

        for i in range(br._PREVIEW_CACHE_SIZE + 3):
            br._original_pixels(NS(name=f"n{i}.jpg", size=10 + i, getvalue=getvalue))
        assert len(cache) == br._PREVIEW_CACHE_SIZE
        assert "a.jpg:1" not in cache  # oldest dropped


def _op(name: OpName, backend: Backend, params=None, bbox=None) -> Op:
    return Op(
        op_name=name,
        params=params or {},
        backend=backend,
        risk_tier=RiskTier.LOW,
        step_id="11111111-1111-4111-8111-111111111111",
        bbox=bbox,
    )


@pytest.mark.parametrize(
    "ops, blocked",
    [
        ([_op(OpName.EXPOSURE, Backend.PIL, {"ev": 1.0})], False),
        ([_op(OpName.BACKGROUND_REPLACE, Backend.GENAI, {"prompt": "x"})], True),
        ([_op(OpName.EXPOSURE, Backend.PHOTOSHOP, {"ev": 1.0})], True),
        ([_op(OpName.FILL_MASK, Backend.PIL)], True),
    ],
)
def test_plan_preview_blocked_reason(ops, blocked):
    import vlm_photo_editor.app.components.batch_review as br

    reason = br.plan_preview_blocked_reason(OpGraph(ops=ops))
    assert (reason is not None) is blocked
    assert br.plan_preview_blocked_reason(None) is not None


# ── Batch panel: preview + Character Focus (whole app under AppTest) ──────────

_MAIN_PY = Path(__file__).resolve().parents[2] / "vlm_photo_editor" / "app" / "main.py"


def test_batch_panel_has_preview_character_focus_and_composition():
    import io
    from types import SimpleNamespace as NS

    from PIL import Image
    from streamlit.testing.v1 import AppTest

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(buf, "JPEG")
    files = [
        NS(name=f"{i}.jpg", size=100 + i, getvalue=lambda b=buf.getvalue(): b) for i in range(2)
    ]
    container = MagicMock(pixels=np.zeros((30, 40, 3), dtype=np.uint8), width=40, height=30)

    at = AppTest.from_file(str(_MAIN_PY))
    at.session_state["upload_widget"] = files
    at.session_state["container"] = container
    at.session_state["_loaded_file_id"] = "0.jpg:100"
    at.run(timeout=90)

    assert not at.exception
    assert any("Image 1 of 2: **0.jpg**" in c.value for c in at.caption)
    assert "Preview" in [h.value for h in at.subheader]
    labels = [sb.label for sb in at.selectbox]
    assert "Character Focus:" in labels and "Composition:" in labels


def _cf_app() -> None:
    import streamlit as st

    from vlm_photo_editor.app import state
    from vlm_photo_editor.app.components import character_focus

    state.init_state()
    if st.session_state.get("_show", True):
        character_focus.render_character_focus_controls("cf")


def test_character_focus_targets_survive_unrendered_run():
    from types import SimpleNamespace as NS

    from streamlit.testing.v1 import AppTest

    model = NS(id="coco", origin="scanned", display_name="COCO", backend=NS(value="onnx"))
    with (
        patch("vlm_photo_editor.detection.ready_models", lambda: [model]),
        patch("vlm_photo_editor.detection.model_labels", lambda m: ["person", "dog"]),
        patch("vlm_photo_editor.detection.model_person_labels", lambda m: ["person"]),
        patch("vlm_photo_editor.detection.model_has_label", lambda m, label: False),
    ):
        at = AppTest.from_function(_cf_app)
        at.session_state["character_focus"] = "coco"
        at.run()
        at.multiselect[0].select("dog").run()
        assert at.session_state["character_focus_targets"] == ["dog"]

        at.session_state["_show"] = False  # panel not rendered: Streamlit drops the widget key
        at.run()
        assert "character_focus_targets" not in at.session_state

        at.session_state["_show"] = True
        at.run()
        assert at.multiselect[0].value == ["dog"]


# ── Mode A: adapt the approved plan per image ─────────────────────────────────


def _op(name, backend=Backend.PIL, params=None):
    # risk_tier is derived from the op catalog (exposure LOW, mask MEDIUM, region_edit HIGH)
    return Op(op_name=name, params=params or {}, backend=backend, step_id="s1")


@pytest.mark.parametrize(
    "ops, ref_ops, expected",
    [
        ([_op(OpName.EXPOSURE)], [_op(OpName.EXPOSURE)], True),
        ([], [_op(OpName.EXPOSURE)], True),  # nothing to do on this image
        ([_op(OpName.MASK)], [_op(OpName.EXPOSURE)], False),
        (
            [_op(OpName.MASK)],
            [_op(OpName.REGION_EDIT, Backend.OPENCV)],
            True,
        ),
        ([_op(OpName.BACKGROUND_REPLACE, Backend.GENAI)], [_op(OpName.EXPOSURE)], False),
        ([_op(OpName.EXPOSURE, Backend.PHOTOSHOP)], [_op(OpName.EXPOSURE)], False),
        (
            [_op(OpName.BACKGROUND_REPLACE, Backend.GENAI)],
            [_op(OpName.BACKGROUND_REPLACE, Backend.GENAI)],
            True,
        ),
    ],
)
def test_within_approved_envelope(ops, ref_ops, expected):
    from vlm_photo_editor.pipeline.batch import within_approved_envelope

    assert within_approved_envelope(OpGraph(ops=ops), OpGraph(ops=ref_ops)) is expected


def _adapt_setup(adapted_ops_by_name, *, fail_names=()):
    """Patches for adapt_plan_to_batch: per-image adapted plan/op_graph keyed by filename."""
    from vlm_photo_editor.schema.plan import HumanPlan

    plans = {name: HumanPlan(steps=[], plan_id=str(uuid.uuid4())) for name in adapted_ops_by_name}

    def adapt(container, reference_plan, intent, prefs, mode, fi, **kw):
        name = container.name
        if name in fail_names:
            raise ValueError("planner exploded")
        return plans[name]

    def compile_(plan, mode, detected_subject=None):
        name = next(n for n, p in plans.items() if p is plan) if plan in plans.values() else "ref"
        ops = adapted_ops_by_name.get(name, [_op(OpName.EXPOSURE, params={"ev": 0.5})])
        return MagicMock(plan=plan, op_graph=OpGraph(ops=ops))

    planner_cls = MagicMock()
    planner_cls.return_value.adapt.side_effect = adapt
    compiler_cls = MagicMock()
    compiler_cls.return_value.compile.side_effect = compile_
    executor_cls = MagicMock()
    executor_cls.return_value.apply.return_value = MagicMock(container="edited", genai_ops=[])
    return plans, planner_cls, compiler_cls, executor_cls


def _named_record(name: str) -> BatchImageRecord:
    rec = _make_record(name)
    rec.container.name = name
    rec.container.width = rec.container.height = 10
    return rec


def _run_adapt(records, ref_plan, ref_graph, planner_cls, compiler_cls, executor_cls, seen=None):
    from vlm_photo_editor.pipeline.batch import adapt_plan_to_batch

    with (
        patch(_PLANNER_PATH, planner_cls),
        patch(_COMPILER_PATH, compiler_cls),
        patch("vlm_photo_editor.ops.executor.Executor", executor_cls),
        patch("vlm_photo_editor.background.providers.default_provider_available", lambda: False),
        patch("vlm_photo_editor.pipeline.batch._image_report", lambda r: "REPORT"),
    ):
        anyio.run(
            adapt_plan_to_batch,
            records,
            ref_plan,
            ref_graph,
            "make it pop",
            None,
            "full",
            None,
            0,
            seen.append if seen is not None else None,
            "ref.jpg",
        )


def test_adapt_plan_to_batch_plans_each_image_and_keeps_plan_image_verbatim():
    ref_plan = _fake_plan()
    ref_graph = OpGraph(ops=[_op(OpName.EXPOSURE, params={"ev": 1.0})])
    ops_a = [_op(OpName.EXPOSURE, params={"ev": 0.2})]
    ops_b = [_op(OpName.EXPOSURE, params={"ev": 1.8})]
    plans, planner_cls, compiler_cls, executor_cls = _adapt_setup({"a.jpg": ops_a, "b.jpg": ops_b})
    records = [_named_record(n) for n in ("ref.jpg", "a.jpg", "b.jpg")]
    seen: list = []

    _run_adapt(records, ref_plan, ref_graph, planner_cls, compiler_cls, executor_cls, seen)

    adapt = planner_cls.return_value.adapt
    adapted_images = sorted(c.args[0].name for c in adapt.call_args_list)
    assert adapted_images == ["a.jpg", "b.jpg"]  # the plan image is NOT re-planned
    assert all(c.args[1] is ref_plan for c in adapt.call_args_list)
    assert all(c.kwargs["image_report"] == "REPORT" for c in adapt.call_args_list)
    by_name = {r.filename: r for r in records}
    assert [r.status for r in records] == [ImageStatus.AUTO_EXECUTED] * 3
    assert by_name["ref.jpg"].plan is ref_plan  # approved plan verbatim
    assert by_name["a.jpg"].plan is plans["a.jpg"] and by_name["b.jpg"].plan is plans["b.jpg"]
    assert by_name["a.jpg"].op_graph.ops[0].params == {"ev": 0.2}
    assert by_name["b.jpg"].op_graph.ops[0].params == {"ev": 1.8}  # different numbers per image
    assert sorted(seen) == sorted(r.image_id for r in records)  # progress once per record


def test_adapt_plan_to_batch_holds_plans_outside_envelope_for_review():
    ref_graph = OpGraph(ops=[_op(OpName.EXPOSURE)])
    risky = [_op(OpName.BACKGROUND_REPLACE, Backend.GENAI, {"prompt": "x"})]
    safe = [_op(OpName.EXPOSURE, params={"ev": 0.3})]
    _, planner_cls, compiler_cls, executor_cls = _adapt_setup(
        {"risky.jpg": risky, "safe.jpg": safe}
    )
    records = [_named_record(n) for n in ("ref.jpg", "risky.jpg", "safe.jpg")]

    _run_adapt(records, _fake_plan(), ref_graph, planner_cls, compiler_cls, executor_cls)

    by_name = {r.filename: r for r in records}
    assert by_name["safe.jpg"].status == ImageStatus.AUTO_EXECUTED
    assert by_name["risky.jpg"].status == ImageStatus.NEEDS_REVIEW
    assert by_name["risky.jpg"].edited_container is None and by_name["risky.jpg"].plan is not None


def test_adapt_plan_to_batch_isolates_planner_failure():
    _, planner_cls, compiler_cls, executor_cls = _adapt_setup(
        {"bad.jpg": [], "ok.jpg": [_op(OpName.EXPOSURE, params={"ev": 0.4})]},
        fail_names=("bad.jpg",),
    )
    records = [_named_record(n) for n in ("bad.jpg", "ok.jpg")]
    seen: list = []

    _run_adapt(
        records,
        _fake_plan(),
        OpGraph(ops=[_op(OpName.EXPOSURE)]),
        planner_cls,
        compiler_cls,
        executor_cls,
        seen,
    )

    by_name = {r.filename: r for r in records}
    assert by_name["bad.jpg"].status == ImageStatus.FAILED
    assert "planner exploded" in by_name["bad.jpg"].error
    assert by_name["ok.jpg"].status == ImageStatus.AUTO_EXECUTED
    assert len(seen) == 2


@pytest.mark.parametrize("applied_current_plan", [True, False])
def test_mode_a_apply_button_returns_for_a_new_plan(applied_current_plan):
    """After results exist, only the plan that was applied counts as executed."""
    import io
    from types import SimpleNamespace as NS

    from PIL import Image
    from streamlit.testing.v1 import AppTest

    import vlm_photo_editor.app.components.batch_review as br
    from vlm_photo_editor.schema.plan import HumanPlan

    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(buf, "JPEG")
    files = [
        NS(name=f"{i}.jpg", size=100 + i, getvalue=lambda b=buf.getvalue(): b) for i in range(2)
    ]
    pixels = np.zeros((30, 40, 3), dtype=np.uint8)
    container = MagicMock(pixels=pixels, width=40, height=30)
    plan = _fake_plan()
    other_plan = HumanPlan(steps=[])
    records = [
        BatchImageRecord(
            filename=f"{i}.jpg",
            container=container,
            edited_container=container,
            status=ImageStatus.AUTO_EXECUTED,
        )
        for i in range(2)
    ]

    at = AppTest.from_file(str(_MAIN_PY))
    at.session_state["upload_widget"] = files
    at.session_state["uploaded_files"] = files  # else upload.render treats it as a new file set
    at.session_state["container"] = container
    at.session_state["_loaded_file_id"] = "0.jpg:100"
    at.session_state["current_plan"] = plan
    at.session_state["current_opgraph"] = OpGraph(ops=[_op(OpName.EXPOSURE, params={"ev": 0.5})])
    at.session_state["plan_approved"] = True
    at.session_state["batch_records"] = records
    applied = plan if applied_current_plan else other_plan
    at.session_state["batch_applied_key"] = br.plan_preview_key(applied, "0.jpg:100")
    at.run(timeout=90)

    assert not at.exception
    keys = [b.key for b in at.button]
    assert ("batch_apply_all_btn" in keys) is (not applied_current_plan)
    assert ("accept_plan_btn" in keys) is (not applied_current_plan)
    assert any("Executed" in s.value for s in at.success) is applied_current_plan
    assert any("replaces the current batch results" in w.value for w in at.warning) is (
        not applied_current_plan
    )
