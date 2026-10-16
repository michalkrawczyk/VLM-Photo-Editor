from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

_UUID1 = "00000000-0000-0000-0000-000000000001"
_UUID2 = "00000000-0000-0000-0000-000000000002"

import numpy as np
import pytest
from pydantic import ValidationError

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.planner.compiler import Compiler, CompilerError
from vlm_photo_editor.planner.repair import plans_equivalent
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode, OpName
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan, HumanStep
from vlm_photo_editor.templates.planner import EXAMPLE_PLANS, build_system_prompt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_anthropic_key() -> bool:
    """Deferred import: a module-level one lands after the _UUID constants (E402)."""
    from vlm_photo_editor.secrets.store import SecretStore

    return SecretStore.has("anthropic")


def _step(
    op_names: list[str],
    op_params: list[dict] | None = None,
    *,
    step_id: str | None = None,
    index: int = 1,
) -> HumanStep:
    return HumanStep(
        step_id=step_id or str(uuid.uuid4()),
        index=index,
        title="t",
        why="w",
        op_names=op_names,
        op_params=op_params or [],
    )


def _plan(*steps: HumanStep, mode: str = "full") -> HumanPlan:
    return HumanPlan(steps=list(steps), mode=mode)


# ---------------------------------------------------------------------------
# allowed_ops_for_mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,expected,excluded",
    [
        ("full", OpName.EXPOSURE, None),
        ("background", OpName.BACKGROUND_REPLACE, OpName.CROP),
        ("frame", OpName.CROP, OpName.EXPOSURE),
    ],
)
def test_allowed_ops_for_mode_membership(mode, expected, excluded):
    ops = allowed_ops_for_mode(mode)
    assert expected in ops
    if excluded is not None:
        assert excluded not in ops


def test_frame_mode_excludes_frame_op():
    # Frame mode only allows crop; VLM decides placement, not a blind center-crop.
    assert OpName.FRAME not in allowed_ops_for_mode("frame")


def test_allowed_ops_for_mode_full_has_all():
    assert allowed_ops_for_mode("full") == set(OpName)


def test_allowed_ops_for_mode_unknown_raises():
    with pytest.raises(KeyError, match="Unknown edit mode"):
        allowed_ops_for_mode("bogus")


# ---------------------------------------------------------------------------
# Compiler — happy path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,params",
    [
        ("crop", {"left": 0, "top": 0, "right": 100, "bottom": 80}),
        ("exposure", {"ev": 1.0}),
        ("rotate", {"angle": 90.0}),
        ("white_balance", {"temperature": 5500.0}),
        ("denoise", {}),
        ("frame", {"mode": "rule_of_thirds"}),
    ],
)
def test_compiler_happy_path(op_name, params):
    step = _step([op_name], [params], step_id=_UUID1)
    result = Compiler().compile(_plan(step), "full")
    assert isinstance(result, CompilerResult)
    assert len(result.op_graph.ops) == 1
    assert result.op_graph.ops[0].op_name.value == op_name
    assert result.op_graph.ops[0].step_id == _UUID1
    assert result.op_graph.ops[0].params == params


# ---------------------------------------------------------------------------
# Compiler — step-ID linkage
# ---------------------------------------------------------------------------


def test_compiler_step_id_linkage():
    s1 = _step(["exposure", "rotate"], [{"ev": 0.5}, {"angle": 45.0}], step_id=_UUID1, index=1)
    s2 = _step(
        ["crop"], [{"left": 0, "top": 0, "right": 200, "bottom": 150}], step_id=_UUID2, index=2
    )
    result = Compiler().compile(_plan(s1, s2), "full")
    assert result.op_graph.ops[0].step_id == _UUID1
    assert result.op_graph.ops[1].step_id == _UUID1
    assert result.op_graph.ops[2].step_id == _UUID2


# ---------------------------------------------------------------------------
# Compiler — op_params padding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_names,op_params",
    [
        (["crop"], []),  # fewer params than names
        (["exposure"], [{"ev": 1.0}, {"ev": 2.0}]),  # more params than names
    ],
)
def test_human_step_rejects_mismatched_op_params_length(op_names, op_params):
    """Schema-level parity validator (S-B1) rejects this before the compiler runs."""
    with pytest.raises(ValidationError, match="op_names.*op_params"):
        _step(op_names, op_params)


# ---------------------------------------------------------------------------
# T4 — crop out-of-bounds validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params,match",
    [
        ({"left": 100, "top": 0, "right": 50, "bottom": 80}, "left.*<.*right"),
        ({"left": 0, "top": 80, "right": 100, "bottom": 40}, "top.*<.*bottom"),
        ({"left": -1, "top": 0, "right": 100, "bottom": 80}, "non-negative"),
    ],
)
def test_crop_out_of_bounds_raises(params, match):
    step = _step(["crop"], [params])
    with pytest.raises(CompilerError, match=match):
        Compiler().compile(_plan(step), "full")


@pytest.mark.parametrize(
    "params,w,h,match",
    [
        # bottom exceeds image height (exact failing case from user report)
        (
            {"left": 0, "top": 0, "right": 992, "bottom": 798},
            1408,
            768,
            "bottom=798 > image height 768",
        ),
        # right exceeds image width
        (
            {"left": 0, "top": 0, "right": 1500, "bottom": 100},
            1408,
            768,
            "right=1500 > image width 1408",
        ),
        # both right and bottom exceed bounds
        (
            {"left": 0, "top": 0, "right": 2000, "bottom": 1000},
            1408,
            768,
            "right=2000 > image width 1408",
        ),
    ],
)
def test_validate_crop_bounds_raises(params, w, h, match):
    from vlm_photo_editor.ops.validator import validate_crop_bounds

    step = _step(["crop"], [params])
    result = Compiler().compile(_plan(step), "full")
    with pytest.raises(ValueError, match=match):
        validate_crop_bounds(result.op_graph, w, h)


def test_validate_crop_bounds_passes_when_within_image():
    from vlm_photo_editor.ops.validator import validate_crop_bounds

    step = _step(["crop"], [{"left": 0, "top": 0, "right": 100, "bottom": 80}])
    result = Compiler().compile(_plan(step), "full")
    validate_crop_bounds(result.op_graph, 200, 200)  # no exception


_BAD_CROP = {"left": 0, "top": 0, "right": 200, "bottom": 50}
_GOOD_CROP = {"left": 0, "top": 0, "right": 80, "bottom": 50}


def _crop_plan(params: dict) -> HumanPlan:
    return _plan(_step(["crop"], [params]))


@pytest.mark.parametrize(
    "bad_attempts,expect_error",
    [
        pytest.param(0, False, id="clean_plan_never_revises"),
        pytest.param(1, False, id="one_bad_crop_repaired"),
        pytest.param(2, False, id="two_bad_crops_repaired_at_cap"),
        pytest.param(3, True, id="budget_exhausted_surfaces_error"),
    ],
)
def test_compile_with_repair_crop_budget(bad_attempts, expect_error):
    """`bad_attempts` = how many plans (initial + revisions) carry the out-of-bounds crop."""
    from vlm_photo_editor.planner.repair import (
        PlanRepairError,
        compile_checked,
        compile_with_repair,
    )

    max_repairs = 2
    served = [bad_attempts]  # plans handed out so far, counting the initial one

    def next_plan() -> HumanPlan:
        n = served[0]
        served[0] += 1
        return _crop_plan(_BAD_CROP if n < bad_attempts else _GOOD_CROP)

    feedback: list[str] = []

    def revise(prev, error):
        feedback.append(error)
        return next_plan()

    served[0] = 0
    first = next_plan()

    def compile_fn(p):
        return compile_checked(p, "full", None, 100, 80)

    if expect_error:
        with pytest.raises(PlanRepairError, match="right=200 > image width 100") as ei:
            compile_with_repair(first, compile_fn, revise, max_repairs)
        assert len(ei.value.notes) == max_repairs
        assert ei.value.plan.steps[0].op_params[0] == _BAD_CROP
        assert len(feedback) == max_repairs
    else:
        result, notes = compile_with_repair(first, compile_fn, revise, max_repairs)
        assert len(notes) == bad_attempts == len(feedback)
        assert result.op_graph.ops[0].params["right"] == 80
    assert all("Revise crop to fit within" in fb for fb in feedback)


@pytest.mark.parametrize(
    "bad_step,match",
    [
        pytest.param(_step(["exposure"], [{"ev": 99}]), "out of bounds", id="param_out_of_bounds"),
        pytest.param(_step(["exposure"], [{"ev": 1, "evv": 2}]), "unknown param", id="typo_key"),
        pytest.param(_step(["mask"], [{}]), "immediately followed", id="mask_without_follower"),
    ],
)
def test_compile_with_repair_fixes_compiler_errors(bad_step, match):
    """Non-crop CompilerErrors get the same bounded repair, with the error as feedback."""
    from vlm_photo_editor.planner.repair import compile_with_repair

    feedback: list[str] = []
    fixed = _plan(_step(["exposure"], [{"ev": 1.0}]))

    def revise(prev, error):
        feedback.append(error)
        return fixed

    result, notes = compile_with_repair(
        _plan(bad_step), lambda p: Compiler().compile(p, "full"), revise, 2
    )
    assert [n.attempt for n in notes] == [1]
    assert match in feedback[0]
    assert result.plan is fixed


def test_compile_with_repair_does_not_retry_environment_errors():
    """PS-strict without Photoshop is not something a revised plan can fix."""
    from vlm_photo_editor.planner.repair import PlanRepairError, compile_with_repair

    revise = MagicMock()
    with (
        patch("vlm_photo_editor.config.settings.get_settings") as gs,
        patch("vlm_photo_editor.planner.compiler._ps_available", return_value=False),
    ):
        gs.return_value.ps_mode = "strict"
        gs.return_value.no_genai = False
        with pytest.raises(PlanRepairError, match="PS-strict") as ei:
            compile_with_repair(
                _plan(_step(["denoise"], [{}])), lambda p: Compiler().compile(p, "full"), revise, 2
            )
    revise.assert_not_called()
    assert ei.value.notes == []


@pytest.mark.parametrize(
    "steps,match",
    [
        pytest.param([(["exposure"], [{"ev": 3.0}])], None, id="ev_3_ok"),
        pytest.param([(["exposure"], [{"ev": 5.0}])], "sanity limit", id="ev_5"),
        pytest.param(
            [(["exposure"], [{"ev": 2.5}]), (["exposure"], [{"ev": 2.5}])],
            "add up to",
            id="ev_steps_add_up",
        ),
        pytest.param([(["rotate"], [{"angle": -4.0}])], None, id="straighten_ok"),
        pytest.param([(["rotate"], [{"angle": 90.0}])], None, id="quarter_turn_ok"),
        pytest.param([(["rotate"], [{"angle": -178.0}])], None, id="near_half_turn_ok"),
        pytest.param([(["rotate"], [{"angle": 35.0}])], "off a right angle", id="rotate_35"),
    ],
)
def test_compile_checked_sanity_guard(steps, match):
    """Valid-but-absurd numbers fail as a repairable CompilerError; sane ones compile."""
    from vlm_photo_editor.planner.compiler import CompilerError
    from vlm_photo_editor.planner.repair import compile_checked

    plan = _plan(*[_step(ops, params, index=i) for i, (ops, params) in enumerate(steps, 1)])
    if match is None:
        compile_checked(plan, "full", None, 100, 80)
        return
    with pytest.raises(CompilerError, match=match) as ei:
        compile_checked(plan, "full", None, 100, 80)
    assert ei.value.repairable


@pytest.mark.parametrize("ex", EXAMPLE_PLANS, ids=lambda e: e["situation"].split(".")[0])
def test_prompt_example_compiles(ex):
    """Every few-shot plan in the prompt must pass the real compiler: a stale example
    would teach the model an op/param the executor rejects."""
    steps = [
        _step([op], [params], index=i)
        for i, (_title, _why, op, params) in enumerate(ex["steps"], 1)
    ]
    plan = HumanPlan(diagnosis=ex["diagnosis"], steps=steps)
    assert plan.diagnosis
    Compiler().compile(plan, "full")  # raises CompilerError if the example is stale


def test_plan_diagnosis_is_optional():
    """Plans from before the field existed (cache, fixtures) still validate."""
    assert HumanPlan.model_validate({"steps": []}).diagnosis == ""
    assert HumanPlan.model_validate({"steps": [], "diagnosis": "d"}).diagnosis == "d"


# ---------------------------------------------------------------------------
# Compiler — mode enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "op_name,mode,params",
    [
        ("exposure", "background", {"ev": 1.0}),
        ("background_replace", "frame", {"prompt": "forest"}),
        ("region_edit", "frame", {"prompt": "blur"}),
        ("frame", "frame", {"mode": "rule_of_thirds"}),
    ],
)
def test_compiler_rejects_op_not_in_mode(op_name, mode, params):
    step = _step([op_name], [params])
    with pytest.raises(CompilerError):
        Compiler().compile(_plan(step, mode=mode), mode)


# ---------------------------------------------------------------------------
# Compiler — error cases
# ---------------------------------------------------------------------------


def test_schema_rejects_unknown_op_name():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HumanStep(step_id=_UUID1, index=1, title="t", why="w", op_names=["sharpen"])


def test_compiler_unknown_mode_raises_compiler_error():
    """PLN-B1: KeyError from allowed_ops_for_mode is wrapped, not raw."""
    step = _step(["exposure"], [{"ev": 1.0}])
    with pytest.raises(CompilerError, match="Unknown edit mode"):
        Compiler().compile(_plan(step), "invalid_mode")


def test_compiler_rejects_bogus_frame_mode():
    """SC-B1: an out-of-vocabulary frame mode is a silent no-op without enum validation."""
    step = _step(["frame"], [{"mode": "bogus"}])
    with pytest.raises(CompilerError, match="not one of"):
        Compiler().compile(_plan(step), "full")


# ---------------------------------------------------------------------------
# Compiler — backend assignment
# ---------------------------------------------------------------------------


from vlm_photo_editor.schema.ops import Backend  # noqa: E402


@pytest.mark.parametrize(
    "op_name,expected_backend",
    [
        ("background_replace", Backend.GENAI),
        ("region_edit", Backend.GENAI),
        ("exposure", Backend.PIL),
        ("crop", Backend.PIL),
    ],
)
def test_compiler_assigns_default_backend(op_name, expected_backend):
    params: dict = {"prompt": "sky"} if op_name in {"background_replace", "region_edit"} else {}
    if op_name == "crop":
        params = {"left": 0, "top": 0, "right": 100, "bottom": 80}
    elif op_name == "exposure":
        params = {"ev": 1.0}
    step = _step([op_name], [params])
    with patch(
        "vlm_photo_editor.planner.compiler.available_genai_providers",
        return_value=["replicate", "openai", "google", "huggingface"],
    ):
        result = Compiler().compile(_plan(step), "full")
    assert result.op_graph.ops[0].backend == expected_backend


def test_compiler_reads_backend_from_op_params():
    step = _step(["background_replace"], [{"backend": "opencv"}])
    result = Compiler().compile(_plan(step), "full")
    op = result.op_graph.ops[0]
    assert op.backend == Backend.OPENCV
    assert "backend" not in op.params  # stripped from params


def test_compiler_raises_on_unknown_backend():
    step = _step(["background_replace"], [{"backend": "turbo", "prompt": "sky"}])
    with pytest.raises(CompilerError, match="unknown backend"):
        Compiler().compile(_plan(step), "full")


def test_compiler_no_genai_redirects_inpaint_to_opencv():
    from unittest.mock import patch

    from vlm_photo_editor.config.settings import AppSettings

    step = _step(["background_replace"], [{"prompt": "remove"}])
    with patch(
        "vlm_photo_editor.config.settings.get_settings",
        return_value=AppSettings(no_genai=True),
    ):
        result = Compiler().compile(_plan(step), "full")
    assert result.op_graph.ops[0].backend == Backend.OPENCV


def test_compiler_no_genai_does_not_affect_non_inpaint_ops():
    from unittest.mock import patch

    from vlm_photo_editor.config.settings import AppSettings

    step = _step(["exposure"], [{"ev": 0.5}])
    with patch(
        "vlm_photo_editor.config.settings.get_settings",
        return_value=AppSettings(no_genai=True),
    ):
        result = Compiler().compile(_plan(step), "full")
    assert result.op_graph.ops[0].backend == Backend.PIL


def test_compiler_no_genai_raises_for_non_inpaint_genai_op():
    """PLN-B4: explicit backend=genai on a non-inpaint op must raise when no_genai=True."""
    from unittest.mock import patch

    from vlm_photo_editor.config.settings import AppSettings

    step = _step(["exposure"], [{"ev": 0.5, "backend": "genai"}])
    with patch(
        "vlm_photo_editor.config.settings.get_settings",
        return_value=AppSettings(no_genai=True),
    ):
        with pytest.raises(CompilerError, match="GenAI is disabled"):
            Compiler().compile(_plan(step), "full")


def test_compiler_genai_op_raises_when_provider_key_missing():
    """Compiler must raise CompilerError when genai op's provider key is absent."""
    step = _step(["region_edit"], [{"prompt": "blur background"}])
    with patch(
        "vlm_photo_editor.planner.compiler.available_genai_providers",
        return_value=[],
    ):
        with pytest.raises(CompilerError, match="replicate"):
            Compiler().compile(_plan(step), "full")


def test_compiler_genai_op_passes_when_provider_key_present():
    """Compiler must accept genai op when provider key is available."""
    step = _step(["region_edit"], [{"prompt": "blur background"}])
    with patch(
        "vlm_photo_editor.planner.compiler.available_genai_providers",
        return_value=["replicate"],
    ):
        result = Compiler().compile(_plan(step), "full")
    genai_ops = [op for op in result.op_graph.ops if op.op_name.value == "region_edit"]
    assert len(genai_ops) == 1


def test_compiler_result_preserves_plan():
    plan = _plan(_step(["denoise"], [{}]))
    result = Compiler().compile(plan, "full")
    assert result.plan is plan


# ---------------------------------------------------------------------------
# Compiler — params shallow copy (mutation safety)
# ---------------------------------------------------------------------------


def test_compiler_params_are_shallow_copied():
    original_params = {"ev": 1.0}
    step = _step(["exposure"], [original_params], step_id=_UUID1)
    result = Compiler().compile(_plan(step), "full")
    result.op_graph.ops[0].params["ev"] = 999.0
    assert original_params["ev"] == 1.0  # step params not mutated


# ---------------------------------------------------------------------------
# Schema — HumanStep op_params round-trip
# ---------------------------------------------------------------------------


def test_human_step_op_params_round_trip():
    step = HumanStep(
        step_id=_UUID1,
        index=1,
        title="t",
        why="w",
        op_names=["exposure"],
        op_params=[{"ev": 1.5}],
    )
    restored = HumanStep.model_validate(step.model_dump())
    assert restored.op_params == [{"ev": 1.5}]
    assert restored.op_names == ["exposure"]


def test_human_step_op_params_defaults_empty():
    step = HumanStep(step_id=_UUID1, index=1, title="t", why="w", op_names=[])
    assert step.op_params == []


# ---------------------------------------------------------------------------
# Planner — mocked LLM
# ---------------------------------------------------------------------------


def _mock_plan() -> HumanPlan:
    return _plan(_step(["exposure"], [{"ev": 1.0}]), mode="full")


def _planner_with_llm(*results):
    """Planner whose mocked structured LLM returns ``results`` in order."""
    from vlm_photo_editor.agents.planner import Planner

    with patch("vlm_photo_editor.agents.planner.build_client") as mock_build:
        mock_llm = MagicMock()
        invoke = mock_llm.with_structured_output.return_value.invoke
        invoke.side_effect = list(results)
        mock_build.return_value = mock_llm
        return Planner(), invoke


def _container():
    container = MagicMock()
    container.pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    container.width = container.height = 64
    return container


@pytest.mark.parametrize("method", ["plan", "revise"])
def test_planner_calls_llm_returns_human_plan(method):
    previous = _mock_plan()
    new_plan = _plan(_step(["exposure"], [{"ev": 2.0}]), mode="full")
    planner, invoke = _planner_with_llm(new_plan)

    if method == "plan":
        result = planner.plan(_container(), intent="make it pop")
    else:
        result = planner.revise(_container(), previous_plan=previous, feedback="brighter")

    assert isinstance(result, HumanPlan)
    assert result.mode == "full"
    invoke.assert_called_once()


def test_revise_prompt_carries_intent_plan_feedback_and_override_rule():
    previous = _mock_plan()
    planner, invoke = _planner_with_llm(_plan(_step(["crop"], [{"left": 0}]), mode="full"))

    planner.revise(
        _container(),
        previous_plan=previous,
        feedback="crop face only",
        original_intent="portrait headroom",
        framing_intent=FramingIntent(
            mode=FramingMode.PORTRAIT_HEADROOM, focus_instruction="f", frame_ratio="4:5"
        ),
    )

    system, human = invoke.call_args.args[0]
    user_text = human.content[1]["text"]
    assert "REVISION RULE" in system.content and "overrides" in system.content
    assert "Target crop" in system.content  # framing constraints still present, but overridable
    assert "ORIGINAL USER INSTRUCTION:\nportrait headroom" in user_text
    assert previous.steps[0].step_id in user_text
    assert "USER FEEDBACK:\ncrop face only" in user_text
    assert "TASK: Adjust the previous plan" in user_text


@pytest.mark.parametrize("mode", ["full", "frame"])
def test_adapt_prompt_follows_reference_but_rederives_for_this_image(mode):
    reference = _plan(_step(["crop"], [{"left": 100, "top": 100, "right": 3000, "bottom": 2000}]))
    adapted = _plan(_step(["crop"], [{"left": 5, "top": 5, "right": 50, "bottom": 40}]))
    planner, invoke = _planner_with_llm(adapted)

    result = planner.adapt(
        _container(),
        reference_plan=reference,
        intent="tighter portrait crop",
        mode=mode,
        framing_intent=FramingIntent(
            mode=FramingMode.PORTRAIT_HEADROOM, focus_instruction="f", frame_ratio="4:5"
        ),
    )

    system, human = invoke.call_args.args[0]
    user_text = human.content[1]["text"]
    assert result is adapted and result.mode == mode
    invoke.assert_called_once()
    assert "ADAPTATION RULE" in system.content and "Target crop" in system.content
    assert "REVISION RULE" not in system.content
    assert "Image dimensions: 64x64" in user_text
    assert "ORIGINAL USER INSTRUCTION:\ntighter portrait crop" in user_text
    assert '"right": 3000' in user_text  # reference plan is shown...
    assert "instead of copying the reference numbers" in user_text  # ...but not to be copied


@pytest.mark.parametrize("second_result_changes", [True, False])
def test_revise_reprompts_once_when_plan_unchanged(second_result_changes):
    previous = _mock_plan()
    echo = _plan(_step(["exposure"], [{"ev": 1.0}]), mode="full")  # same ops/params, new ids
    changed = _plan(_step(["exposure"], [{"ev": 2.0}]), mode="full")
    planner, invoke = _planner_with_llm(echo, changed if second_result_changes else echo)

    result = planner.revise(_container(), previous_plan=previous, feedback="brighter")

    assert invoke.call_count == 2  # one retry, never a third call
    assert plans_equivalent(previous, result) is (not second_result_changes)
    retry_text = invoke.call_args_list[1].args[0][1].content[1]["text"]
    assert "identical to the PREVIOUS PLAN" in retry_text


@pytest.mark.parametrize(
    "other, expected",
    [
        (_plan(_step(["exposure"], [{"ev": 1.0}])), True),
        (_plan(_step(["exposure"], [{"ev": 1.5}])), False),
        (_plan(_step(["tone"], [{"shadows": 10}])), False),
        (_plan(_step(["exposure"], [{"ev": 1.0}]), _step(["denoise"], [{}])), False),
        (_plan(), False),
    ],
)
def test_plans_equivalent(other, expected):
    assert plans_equivalent(_plan(_step(["exposure"], [{"ev": 1.0}])), other) is expected


@pytest.mark.parametrize(
    "provider, expected_kwargs",
    [
        ("anthropic", {}),
        ("local", {}),
        ("openai", {"method": "function_calling"}),
    ],
)
def test_planner_structured_output_method_per_provider(provider, expected_kwargs):
    """OpenAI's strict json_schema can't express HumanPlan.op_params — the planner must
    request method='function_calling' for that provider only."""
    from vlm_photo_editor.config.registry import ModelEntry

    with (
        patch("vlm_photo_editor.agents.planner.build_client") as mock_build,
        patch(
            "vlm_photo_editor.config.registry.ModelRegistry.get_entry",
            return_value=ModelEntry("m", provider=provider),
        ),
    ):
        mock_llm = MagicMock()
        mock_build.return_value = mock_llm

        from vlm_photo_editor.agents.planner import Planner

        Planner()

        mock_llm.with_structured_output.assert_called_once_with(HumanPlan, **expected_kwargs)


def test_planner_logs_via_structlog_not_stdlib():
    """AGT-D2: stdlib logging bypasses the structlog RedactionProcessor — the VLM
    prompt (which may echo a key-like string) must be logged through structlog."""
    import logging as _stdlib_logging

    from vlm_photo_editor.agents import planner as planner_mod

    assert not hasattr(planner_mod, "_log")
    assert not hasattr(planner_mod, "logging")
    assert not isinstance(planner_mod.log, _stdlib_logging.Logger)
    assert type(planner_mod.log).__module__.startswith("structlog")


# ---------------------------------------------------------------------------
# Planner._user_content — dimensions in message
# ---------------------------------------------------------------------------


def test_user_content_includes_dimensions():
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.zeros((48, 80, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/img.jpg"),
    )
    with patch("vlm_photo_editor.agents.planner.build_client"):
        planner = Planner()

    content = planner._user_content(container, "crop tightly")
    text_block = next(b for b in content if b.get("type") == "text")["text"]
    assert "80x48" in text_block  # width x height
    assert "Edit intent: crop tightly" in text_block


# ---------------------------------------------------------------------------
# Image report — MEASUREMENTS block, rules, VLM input hygiene
# ---------------------------------------------------------------------------


def _report(**overrides):
    from vlm_photo_editor.schema.report import ExifSummary, ImageReport

    base = dict(
        width=80,
        height=48,
        luma_mean=0.41,
        luma_p1=0.02,
        luma_p5=0.05,
        luma_p50=0.38,
        luma_p95=0.81,
        luma_p99=0.9,
        clipped_shadow_pct=0.0,
        clipped_highlight_pct=4.2,
        channel_means=(0.4, 0.4, 0.4),
        cast_rb_ratio=1.31,
        cast_label="warm",
        suggested_wb_temperature=5200.0,
        saturation_mean=0.31,
        sharpness=120.0,
        noise_sigma=1.2,
        tilt_deg=1.8,
        tilt_confidence=0.82,
        exif=ExifSummary(iso=800, exposure_time_s=1 / 125, f_number=2.8, wb_mode="manual"),
    )
    return ImageReport(**{**base, **overrides})


def _planner_and_container(shape=(48, 80, 3), dtype=np.uint8, fill=0, icc=None):
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.full(shape, fill, dtype=dtype),
        bit_depth=16 if dtype == np.uint16 else 8,
        source_path=Path("/fake/img.jpg"),
        icc_profile=icc,
    )
    with patch("vlm_photo_editor.agents.planner.build_client"):
        return Planner(), container


def _text_of(content) -> str:
    return next(b for b in content if b.get("type") == "text")["text"]


def test_measurements_only_when_report_given():
    planner, container = _planner_and_container()

    plain = _text_of(planner._user_content(container, "fix it"))
    assert "MEASUREMENTS" not in plain
    assert "MEASUREMENT RULES" not in build_system_prompt("full", None, None, None)

    text = _text_of(planner._user_content(container, "fix it", image_report=_report()))
    assert "MEASUREMENTS (computed from the pixels" in text
    assert "highlights 4.2%" in text
    assert "cast warm (R/B 1.31)" in text and "suggested white_balance temperature 5200" in text
    assert "tilt +1.8 deg" in text and "rotate by -1.8" in text
    assert "ISO 800, 1/125 s, f/2.8, manual WB" in text
    assert text.index("MEASUREMENTS") < text.index("Edit intent:")  # intent stays last

    rules = build_system_prompt("full", None, None, None, image_report=_report())
    assert "MEASUREMENT RULES" in rules


def test_measurements_handle_missing_tilt_and_exif():
    from vlm_photo_editor.schema.report import ExifSummary

    planner, container = _planner_and_container()
    report = _report(tilt_deg=None, tilt_confidence=None, exif=ExifSummary())
    text = _text_of(planner._user_content(container, "x", image_report=report))
    assert "no dominant horizontal/vertical lines" in text
    assert "Camera:" not in text


def test_large_image_is_downscaled_and_coordinate_space_stated():
    import base64
    import io

    from PIL import Image

    planner, container = _planner_and_container(shape=(2000, 3000, 3), fill=90)
    content = planner._user_content(container, "x")
    text = _text_of(content)
    assert "Image dimensions: 3000x2000" in text
    assert "Image sent to you: 1568x1045" in text and "ORIGINAL pixel space" in text

    url = content[0]["image_url"]["url"]
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert sent.size == (1568, 1045)

    small_planner, small = _planner_and_container()
    assert "Image sent to you" not in _text_of(small_planner._user_content(small, "x"))


def test_uint16_image_is_not_contrast_stretched():
    import base64
    import io

    from PIL import Image

    # A dark 16-bit frame (value 4000/65535 ~ 6 %) used to be stretched to full range.
    planner, container = _planner_and_container(dtype=np.uint16, fill=4000)
    img = Image.open(io.BytesIO(base64.b64decode(planner._encode_image(container))))
    assert np.asarray(img).mean() < 30


def test_bad_icc_profile_does_not_block_encoding():
    planner, container = _planner_and_container(icc=b"definitely not an icc profile")
    assert planner._encode_image(container)


# ---------------------------------------------------------------------------
# frame_target_size — pure utility
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "w,h,composition,expected",
    [
        (4000, 3000, "rule_of_thirds", (4000, 3000)),  # 4:3 matches exactly
        (4000, 3000, "portrait_headroom", (2250, 3000)),  # wider than 3:4 → crop width
        (3000, 4000, "portrait_headroom", (3000, 4000)),  # already 3:4 (within int rounding)
        (3000, 3000, "center_symmetry", (3000, 3000)),  # 1:1 square
        (1920, 1080, "negative_space", (1920, 1080)),  # 16:9 matches exactly
        (4000, 3000, "fill_frame", None),  # no-op → None
    ],
)
def test_frame_target_size(w, h, composition, expected):
    from vlm_photo_editor.ops.backends.pil_backend import frame_target_size

    assert frame_target_size(w, h, composition) == expected


# ---------------------------------------------------------------------------
# Planner._system_prompt — framing instructions injected when composition set
# ---------------------------------------------------------------------------


def test_system_prompt_includes_framing_instructions():
    fi = FramingIntent(
        mode=FramingMode.PORTRAIT_HEADROOM,
        focus_instruction="Leave breathing room above the head.",
        frame_ratio="3:4",
    )
    prompt = build_system_prompt("frame", None, fi, (2250, 3000))
    assert "FRAMING INSTRUCTIONS" in prompt
    assert "portrait_headroom" in prompt
    assert "2250" in prompt
    assert "3000" in prompt
    assert "right - left == 2250" in prompt


def test_system_prompt_no_framing_without_composition():
    prompt = build_system_prompt("frame", None, None, None)
    assert "FRAMING INSTRUCTIONS" not in prompt


# ---------------------------------------------------------------------------
# Planner._user_content — target frame line injected when composition set
# ---------------------------------------------------------------------------


def test_user_content_includes_target_frame():
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.zeros((3000, 4000, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/img.jpg"),
    )
    with patch("vlm_photo_editor.agents.planner.build_client"):
        planner = Planner()

    content = planner._user_content(
        container, "frame me", composition="portrait_headroom", target_size=(2250, 3000)
    )
    text_block = next(b for b in content if b.get("type") == "text")["text"]
    assert "Target frame: 2250x3000" in text_block
    assert "portrait_headroom" in text_block


def test_user_content_no_target_frame_without_composition():
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.zeros((48, 80, 3), dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/img.jpg"),
    )
    with patch("vlm_photo_editor.agents.planner.build_client"):
        planner = Planner()

    content = planner._user_content(container, "brighten")
    text_block = next(b for b in content if b.get("type") == "text")["text"]
    assert "Target frame" not in text_block


# ---------------------------------------------------------------------------
# T1 — _encode_image handles 16-bit (RAW) containers without crashing (B1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_encode_image_handles_bit_depth(dtype):
    import base64
    import io as _io
    from pathlib import Path

    from PIL import Image as PILImage

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    pixels = np.full((32, 32, 3), 32768 if dtype == np.uint16 else 128, dtype=dtype)
    container = ImageContainer(
        pixels=pixels,
        bit_depth=16 if dtype == np.uint16 else 8,
        source_path=Path("/fake/img.cr2"),
    )
    with patch("vlm_photo_editor.agents.planner.build_client"):
        planner = Planner()

    b64 = planner._encode_image(container)
    img = PILImage.open(_io.BytesIO(base64.b64decode(b64)))
    assert img.size == (32, 32)


# ---------------------------------------------------------------------------
# Integration — real LLM round-trip (skipped in CI unless API key present)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(not _has_anthropic_key(), reason="requires ANTHROPIC_API_KEY")
def test_planner_compile_round_trip_integration():
    """Requires ANTHROPIC_API_KEY. Verifies end-to-end plan → compile."""
    from pathlib import Path

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer

    container = ImageContainer(
        pixels=np.full((64, 64, 3), 128, dtype=np.uint8),
        bit_depth=8,
        source_path=Path("/fake/test.jpg"),
    )
    plan = Planner().plan(container, intent="Brighten and crop", mode="full")
    assert len(plan.steps) >= 1

    result = Compiler().compile(plan, "full")
    assert len(result.op_graph.ops) >= 1
    step_ids = {s.step_id for s in plan.steps}
    for op in result.op_graph.ops:
        assert op.step_id in step_ids
