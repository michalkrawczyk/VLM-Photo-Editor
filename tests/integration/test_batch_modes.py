"""Batch two-mode integration — real Compiler + real Executor, planner mocked.

Mode A (``apply_plan_to_batch``): one already-approved ``HumanPlan`` recompiled
against every image's dimensions/subject and executed, no VLM call.
Mode B (``run_batch``): each record's own ``intent`` reaches the planner; a blank
override falls back to the shared batch-wide instruction.

Only the VLM planner is a test double — the same convention as
``tests/integration/test_p8_5_mvp_gate.py``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import anyio
import pytest

from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.pipeline.batch import apply_plan_to_batch, run_batch
from vlm_photo_editor.schema.batch import BatchImageRecord, ImageStatus
from vlm_photo_editor.schema.ops import AcceptMode
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "face_portrait.jpg"


def _plan() -> HumanPlan:
    return HumanPlan(
        steps=[
            HumanStep(
                step_id=str(uuid.uuid4()),
                index=1,
                title="Brighten",
                why="lift shadows",
                op_names=["exposure"],
                op_params=[{"ev": 0.3}],
            )
        ],
        mode="full",
    )


def _load_copies(tmp_path: Path, n: int) -> list:
    out = []
    for i in range(n):
        dst = tmp_path / f"img{i}.jpg"
        dst.write_bytes(_FIXTURE.read_bytes())
        out.append(load(dst))
    return out


def test_mode_a_recompiles_one_plan_and_executes_every_image(tmp_path: Path) -> None:
    containers = _load_copies(tmp_path, 3)
    records = [
        BatchImageRecord(filename=f"img{i}.jpg", container=c) for i, c in enumerate(containers)
    ]
    approved = _plan()
    step_id = approved.steps[0].step_id

    out = apply_plan_to_batch(records, approved, "full")

    assert out is records
    assert all(r.status == ImageStatus.AUTO_EXECUTED for r in records)
    # Each image got its own freshly compiled graph, all tracing to the approved step.
    assert len({id(r.op_graph) for r in records}) == 3
    for r in records:
        assert r.op_graph is not None
        assert {o.step_id for o in r.op_graph.ops} == {step_id}
        assert r.edited_container is not None
        assert r.edited_container is not r.container


def test_mode_b_threads_each_records_own_intent_with_shared_fallback(tmp_path: Path) -> None:
    containers = _load_copies(tmp_path, 3)
    intents = ["make it noticeably warmer", "", "cooler tones"]
    records = [
        BatchImageRecord(filename=f"img{i}.jpg", container=c, intent=intents[i])
        for i, c in enumerate(containers)
    ]

    seen: list[str] = []

    def fake_plan(container, intent, prefs, mode, fi, detected_subject=None, genai_available=True):
        seen.append(intent)
        return _plan()

    mock_planner = MagicMock()
    mock_planner.return_value.plan.side_effect = fake_plan

    with (
        patch("vlm_photo_editor.agents.planner.Planner", mock_planner),
        patch(
            "vlm_photo_editor.background.providers.default_provider_available",
            lambda: False,
        ),
    ):
        anyio.run(
            run_batch,
            records,
            "SHARED FALLBACK",
            None,
            "full",
            None,
            AcceptMode.FULL_AUTO,
            0,
            None,
        )

    # blank override -> shared fallback; the rest use their own instruction
    assert sorted(seen) == sorted(["make it noticeably warmer", "SHARED FALLBACK", "cooler tones"])
    assert all(r.status == ImageStatus.AUTO_EXECUTED for r in records)
