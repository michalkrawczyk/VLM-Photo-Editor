"""P8.5 MVP Integration Gate — deterministic invariants.

Verification gate for build-plan step P8.5. Proves the four MVP capabilities
(background edit, subject-aware framing, small corrections, preference learning)
compose through the *real* Compiler / Executor / recipe-store / preference-store
chain — the VLM planner and the genAI provider are the only test doubles.

The whole-flow pass against the live app + real Anthropic API is the Playwright
suite in ``tests/e2e/test_full_edit_and_framing.py`` (opt-in, ``pytest -m e2e``).

"API keys are never exposed / logged / stored in plaintext" is covered by
``tests/unit/test_secrets.py``; here we only assert the recipe sidecar records the
model name and nothing key-like.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from vlm_photo_editor.agents.aggregator import Aggregator
from vlm_photo_editor.agents.edit_flow import _can_auto_approve
from vlm_photo_editor.background.providers.base import Candidate, GenAIProvider
from vlm_photo_editor.imageio.loaders import load
from vlm_photo_editor.imageio.savers import save as _save
from vlm_photo_editor.ops.executor import Executor
from vlm_photo_editor.planner.compiler import Compiler, CompilerError
from vlm_photo_editor.preferences.store import DeltaStore, PreferenceStore
from vlm_photo_editor.recipe.renderer import Renderer
from vlm_photo_editor.recipe.store import RecipeStore
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import AcceptMode, BoundingBox, OpName, RiskTier
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep
from vlm_photo_editor.schema.prefs import EditDelta
from vlm_photo_editor.schema.recipe import GenAIOp, Recipe
from vlm_photo_editor.templates.planner import build_system_prompt

pytestmark = pytest.mark.integration

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "face_portrait.jpg"


# --------------------------------------------------------------------------- #
# Test doubles / helpers                                                      #
# --------------------------------------------------------------------------- #


class _FakeProvider(GenAIProvider):
    """Deterministic stand-in for a genAI backend: fills the masked region with a
    distinct flat colour per candidate and records model/prompt/seed verbatim
    (seed passed straight through — ``None`` stays ``None``, BG-P2)."""

    def generate(self, container, mask, prompt, model, step_id, n=3, seed=None, **kwargs):
        out: list[Candidate] = []
        for i in range(n):
            c = container.copy()
            c.pixels[mask] = (37 * (i + 1)) % 250
            out.append(
                Candidate(
                    container=c,
                    genai_op=GenAIOp(step_id=step_id, model=model, prompt=prompt, seed=seed),
                )
            )
        return out


class _BoomProvider(GenAIProvider):
    def generate(self, *args, **kwargs):
        raise RuntimeError("provider down")


@contextmanager
def _fake_genai(provider_factory=lambda model: _FakeProvider()) -> Iterator[None]:
    """Make GENAI ops compilable + executable without keys: pretend a replicate
    provider is available, and hand the pipeline a local fake."""
    with (
        patch(
            "vlm_photo_editor.planner.compiler.available_genai_providers",
            return_value=["replicate"],
        ),
        patch("vlm_photo_editor.background.get_provider", provider_factory),
    ):
        yield


def _step(op_names, op_params, *, step_id: str | None = None, index: int = 1) -> HumanStep:
    return HumanStep(
        step_id=step_id or str(uuid.uuid4()),
        index=index,
        title="t",
        why="w",
        op_names=op_names,
        op_params=op_params,
    )


def _plan(*steps: HumanStep, mode: str = "full") -> HumanPlan:
    return HumanPlan(steps=list(steps), mode=mode)


def _fixture_image(tmp_path: Path):
    """Copy the tracked 150x200 fixture into ``tmp_path`` and load it, so the
    save / byte-identical assertions run against a throwaway original."""
    dst = tmp_path / "face_portrait.jpg"
    dst.write_bytes(_FIXTURE.read_bytes())
    return load(dst), dst


def _inject_region_bbox(op_graph, box: BoundingBox):
    """The ``_REGION_OPS`` branch of ``app/main.py:284-294`` (drawn-region injection),
    lifted so the gate exercises what the app really runs. Keep in sync with that block."""
    region_ops = {OpName.BACKGROUND_REPLACE, OpName.REGION_EDIT, OpName.FILL_MASK}
    patched = []
    for op in op_graph.ops:
        if op.bbox is None and op.params.get("invert") is True:
            op = op.model_copy(update={"bbox": box})
        elif op.op_name in region_ops:
            op = op.model_copy(update={"bbox": box, "params": {**op.params, "invert": False}})
        patched.append(op)
    return op_graph.model_copy(update={"ops": patched})


def _only(op_graph, *keep: OpName):
    return op_graph.model_copy(update={"ops": [o for o in op_graph.ops if o.op_name in keep]})


# --------------------------------------------------------------------------- #
# DoD line 209 — one image through the whole combo, original untouched        #
# --------------------------------------------------------------------------- #


def test_manual_background_reframe_and_correction_all_apply_then_save_preserves_original(
    tmp_path: Path,
) -> None:
    img, src_path = _fixture_image(tmp_path)
    orig_bytes = src_path.read_bytes()

    s1, s2, s3 = (str(uuid.uuid4()) for _ in range(3))
    # "revised" plan: background edit + framing + a small correction, one step each.
    revised = _plan(
        _step(["background_replace"], [{"prompt": "forest"}], step_id=s1, index=1),
        _step(["frame"], [{"mode": "rule_of_thirds"}], step_id=s2, index=2),
        _step(["exposure"], [{"ev": 0.4}], step_id=s3, index=3),
    )

    with _fake_genai():
        result = Compiler().compile(revised, "full")

        # stable-ID linkage: every compiled op traces back to a plan step
        assert {o.step_id for o in result.op_graph.ops} == {s1, s2, s3}
        bg_op = next(o for o in result.op_graph.ops if o.op_name == OpName.BACKGROUND_REPLACE)
        assert bg_op.risk_tier is RiskTier.HIGH

        # manual mode: a HIGH-risk op never auto-approves — the user approves here
        assert _can_auto_approve(result.op_graph, AcceptMode.MANUAL) is False

        og = _inject_region_bbox(result.op_graph, BoundingBox(x=20, y=20, width=60, height=60))
        res = Executor().apply(img, og)

        frame_only = Executor().apply(img, _only(og, OpName.FRAME)).container
        bg_frame = (
            Executor().apply(img, _only(og, OpName.BACKGROUND_REPLACE, OpName.FRAME)).container
        )

    # framing changed the geometry
    assert (res.container.width, res.container.height) != (img.width, img.height)
    # background op actually did something
    assert not np.array_equal(bg_frame.pixels, frame_only.pixels)
    # exposure brightened the result relative to the same graph without it
    assert res.container.pixels.mean() > bg_frame.pixels.mean()
    # genAI op recorded model + prompt; seed never fabricated
    assert len(res.genai_ops) == 1
    assert res.genai_ops[0].prompt == "forest"
    assert res.genai_ops[0].model
    assert res.genai_ops[0].seed is None or isinstance(res.genai_ops[0].seed, int)

    # save writes a new file; the original on disk is byte-identical
    saved = _save(res.container, tmp_path / "out" / "face_portrait_edited.jpg")
    assert saved.exists()
    assert src_path.read_bytes() == orig_bytes
    with pytest.raises(ValueError, match="overwrite source"):
        _save(img, img.source_path)

    # recipe sidecar: replayable, step-IDs preserved, model name only (no key)
    recipe = Recipe(source_path="face_portrait.jpg", op_graph=og, genai_ops=res.genai_ops)
    sidecar = RecipeStore.save(recipe, directory=tmp_path)
    assert sidecar.name == "face_portrait.edit.json" and sidecar.exists()
    reloaded = RecipeStore.load(sidecar)
    assert [o.step_id for o in reloaded.op_graph.ops] == [s1, s2, s3]
    text = sidecar.read_text()
    assert "flux-fill-dev" in text
    assert "sk-" not in text and "r8_" not in text

    with _fake_genai():
        r1 = Renderer().render(recipe, img).container.pixels
        r2 = Renderer().render(recipe, img).container.pixels
    assert np.array_equal(r1, r2)  # deterministic replay


# --------------------------------------------------------------------------- #
# "Subject is never touched" (Principle 6)                                    #
# --------------------------------------------------------------------------- #


def test_masked_region_edit_leaves_subject_pixels_bit_identical(tmp_path: Path) -> None:
    img, _ = _fixture_image(tmp_path)
    subject = DetectedSubject(
        bbox=BoundingBox(x=30, y=40, width=70, height=90),
        label="person",
        confidence=0.9,
        source="test",
    )
    plan = _plan(
        _step(["mask"], [{}], index=1),
        _step(["region_edit"], [{"method": "blur", "backend": "opencv"}], index=2),
    )
    og = Compiler().compile(plan, "full", detected_subject=subject).op_graph
    assert [o.op_name for o in og.ops] == [OpName.REGION_EDIT]  # mask folded in
    assert og.ops[0].params["invert"] is True

    out = Executor().apply(img, og).container
    assert np.array_equal(out.pixels[40:130, 30:100], img.pixels[40:130, 30:100])
    assert not np.array_equal(out.pixels, img.pixels)  # everything else did change


# --------------------------------------------------------------------------- #
# Accept-mode risk gating on *real* compiled graphs (DoD line 210)           #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "accept_mode, steps, expected",
    [
        (AcceptMode.MANUAL, [_step(["exposure"], [{"ev": 0.2}])], False),
        (
            AcceptMode.AUTO_LOW,
            [
                _step(["exposure"], [{"ev": 0.2}], index=1),
                _step(["frame"], [{"mode": "rule_of_thirds"}], index=2),
            ],
            True,
        ),
        (AcceptMode.AUTO_LOW, [_step(["fill_mask"], [{}])], False),
        (AcceptMode.AUTO_MEDIUM, [_step(["fill_mask"], [{}])], True),
        (AcceptMode.AUTO_MEDIUM, [_step(["background_replace"], [{"prompt": "x"}])], False),
        (AcceptMode.FULL_AUTO, [_step(["background_replace"], [{"prompt": "x"}])], True),
    ],
)
def test_accept_mode_auto_approves_only_within_its_risk_tier(
    accept_mode: AcceptMode, steps: list[HumanStep], expected: bool
) -> None:
    with _fake_genai():
        og = Compiler().compile(_plan(*steps), "full").op_graph
    assert _can_auto_approve(og, accept_mode) is expected


def test_full_auto_executes_high_risk_genai_plan_with_no_human_gate(tmp_path: Path) -> None:
    img, _ = _fixture_image(tmp_path)
    with _fake_genai():
        og = (
            Compiler()
            .compile(_plan(_step(["background_replace"], [{"prompt": "meadow"}])), "full")
            .op_graph
        )
        assert _can_auto_approve(og, AcceptMode.FULL_AUTO) is True
        og = _inject_region_bbox(og, BoundingBox(x=10, y=10, width=80, height=80))
        res = Executor().apply(img, og)
    assert res.container.pixels.shape == img.pixels.shape
    assert len(res.genai_ops) == 1


def test_auto_low_executes_low_risk_plan_end_to_end(tmp_path: Path) -> None:
    img, _ = _fixture_image(tmp_path)
    og = (
        Compiler()
        .compile(
            _plan(
                _step(["exposure"], [{"ev": 0.3}], index=1),
                _step(["frame"], [{"mode": "rule_of_thirds"}], index=2),
            ),
            "full",
        )
        .op_graph
    )
    assert _can_auto_approve(og, AcceptMode.AUTO_LOW) is True
    out = Executor().apply(img, og).container
    assert (out.width, out.height) != (img.width, img.height)


# --------------------------------------------------------------------------- #
# genAI ceiling — existing per-op candidate bound only (P8.5 scoping)         #
# --------------------------------------------------------------------------- #


def test_genai_candidate_count_above_eight_is_rejected_by_validation(tmp_path: Path) -> None:
    # The aggregate per-run genAI ceiling stays a tracked open item under P11; the
    # gate verifies only the existing per-op n bound (op_catalog PARAM_BOUNDS).
    img, _ = _fixture_image(tmp_path)
    with _fake_genai():
        with pytest.raises((CompilerError, ValueError), match=r"n.*\[1, 8\]"):
            Compiler().compile(
                _plan(_step(["background_replace"], [{"prompt": "x", "n": 9}])), "full"
            )

        sid = str(uuid.uuid4())
        og = (
            Compiler()
            .compile(
                _plan(_step(["background_replace"], [{"prompt": "x", "n": 3}], step_id=sid)),
                "full",
            )
            .op_graph
        )
        og = _inject_region_bbox(og, BoundingBox(x=10, y=10, width=80, height=80))
        res = Executor().apply(img, og)
    assert len(res.genai_candidates.get(sid, [])) <= 3


# --------------------------------------------------------------------------- #
# Preference learning changes the next plan (DoD line 212)                    #
# --------------------------------------------------------------------------- #


def test_approved_learned_preference_appears_in_next_planner_prompt(tmp_path: Path) -> None:
    img, _ = _fixture_image(tmp_path)

    ds = DeltaStore(tmp_path / "deltas.jsonl")
    ds.append(
        EditDelta(
            intent="improve portrait",
            mode="full",
            change_requests=["make it warmer"],
            accepted_ops=["exposure"],
        )
    )

    resp = MagicMock()
    resp.content = '{"rules":[{"description":"prefer warmer tones","confidence":0.9}]}'
    with patch("vlm_photo_editor.agents.aggregator.build_client") as mock_build:
        client = MagicMock()
        client.invoke.return_value = resp
        mock_build.return_value = client
        candidates = Aggregator().aggregate(ds.list())
    assert candidates and candidates[0].approved is False

    ps = PreferenceStore(tmp_path / "prefs.json")
    ps.add_learned(candidates)
    before = build_system_prompt("full", ps.load(), None, None)
    assert "prefer warmer tones" not in before  # candidate not approved yet

    ps.approve_learned(candidates[0].rule_id)
    after = build_system_prompt("full", ps.load(), None, None)
    assert "LEARNED PREFERENCES:" in after
    assert "prefer warmer tones" in after
    assert after != before

    # ...and it reaches the *next* planner call
    captured: dict[str, str] = {}

    def _fake_invoke(messages):
        captured["system"] = messages[0].content
        return _plan(_step(["exposure"], [{"ev": 0.1}]))

    with patch("vlm_photo_editor.agents.planner.build_client") as mock_build:
        llm = MagicMock()
        llm.with_structured_output.return_value.invoke.side_effect = _fake_invoke
        mock_build.return_value = llm
        from vlm_photo_editor.agents.planner import Planner

        Planner().plan(img, "improve portrait", prefs=ps.load(), mode="full")
    assert "prefer warmer tones" in captured["system"]


# --------------------------------------------------------------------------- #
# Failures are surfaced, never silently dropped                              #
# --------------------------------------------------------------------------- #


def test_compiler_rejects_out_of_bounds_param_with_an_explicit_error() -> None:
    with pytest.raises(CompilerError, match=r"ev.*out of bounds"):
        Compiler().compile(_plan(_step(["exposure"], [{"ev": 99}])), "full")


def test_executor_propagates_provider_failure_instead_of_returning_a_partial_result(
    tmp_path: Path,
) -> None:
    img, _ = _fixture_image(tmp_path)
    with _fake_genai(provider_factory=lambda model: _BoomProvider()):
        og = (
            Compiler()
            .compile(_plan(_step(["background_replace"], [{"prompt": "x"}])), "full")
            .op_graph
        )
        og = _inject_region_bbox(og, BoundingBox(x=5, y=5, width=50, height=50))
        with pytest.raises(RuntimeError, match="provider down"):
            Executor().apply(img, og)
