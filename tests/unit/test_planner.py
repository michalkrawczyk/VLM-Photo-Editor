from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

_UUID1 = "00000000-0000-0000-0000-000000000001"
_UUID2 = "00000000-0000-0000-0000-000000000002"

import numpy as np
import pytest

from vlm_photo_editor.config.policy import allowed_ops_for_mode
from vlm_photo_editor.planner.compiler import Compiler, CompilerError
from vlm_photo_editor.schema.ops import FramingIntent, FramingMode, OpName
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan, HumanStep
from vlm_photo_editor.templates.planner import build_system_prompt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
def test_compiler_rejects_mismatched_op_params_length(op_names, op_params):
    step = _step(op_names, op_params)
    with pytest.raises(CompilerError, match="op_params length"):
        Compiler().compile(_plan(step), "full")


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


def test_compiler_unknown_mode_raises_key_error():
    step = _step(["exposure"], [{"ev": 1.0}])
    with pytest.raises(KeyError):
        Compiler().compile(_plan(step), "invalid_mode")


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


@pytest.mark.parametrize("method", ["plan", "revise"])
def test_planner_calls_llm_returns_human_plan(method):
    mock_plan = _mock_plan()

    with patch("vlm_photo_editor.agents.planner.build_client") as mock_build:
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value.invoke.return_value = mock_plan
        mock_build.return_value = mock_llm

        from vlm_photo_editor.agents.planner import Planner

        container = MagicMock()
        container.pixels = np.zeros((64, 64, 3), dtype=np.uint8)

        planner = Planner()

        if method == "plan":
            result = planner.plan(container, intent="make it pop")
        else:
            result = planner.revise(container, previous_plan=mock_plan, feedback="brighter")

        assert isinstance(result, HumanPlan)
        assert result.mode == "full"
        mock_llm.with_structured_output.return_value.invoke.assert_called_once()


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
