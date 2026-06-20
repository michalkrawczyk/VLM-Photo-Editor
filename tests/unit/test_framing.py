from __future__ import annotations

import pytest

from vlm_photo_editor.schema.ops import FramingIntent, FramingMode
from vlm_photo_editor.schema.plan import HumanPlan
from vlm_photo_editor.schema.prefs import ExplicitRule, Preferences
from vlm_photo_editor.templates.framing import focus_instruction, frame_ratio_str
from vlm_photo_editor.templates.planner import build_system_prompt

# ---------------------------------------------------------------------------
# DoD #3 — focus instructions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [m for m in FramingMode if m is not FramingMode.RECOMMEND_BEST])
def test_focus_instruction_non_empty(mode):
    assert focus_instruction(mode) != ""


def test_recommend_best_focus_instruction_empty():
    assert focus_instruction(FramingMode.RECOMMEND_BEST) == ""


@pytest.mark.parametrize(
    "mode,expected",
    [
        (FramingMode.RULE_OF_THIRDS, "4:3"),
        (FramingMode.PORTRAIT_HEADROOM, "3:4"),
        (FramingMode.FILL_FRAME, None),
        (FramingMode.RECOMMEND_BEST, None),
    ],
)
def test_frame_ratio_str(mode, expected):
    assert frame_ratio_str(mode) == expected


# ---------------------------------------------------------------------------
# DoD #2 — outpaint flag propagates
# ---------------------------------------------------------------------------


def test_outpaint_needed_field_in_human_plan():
    plan = HumanPlan(steps=[], outpaint_needed=True)
    assert plan.outpaint_needed is True
    assert HumanPlan.model_validate_json(plan.model_dump_json()).outpaint_needed is True


# ---------------------------------------------------------------------------
# DoD #4 — RECOMMEND_BEST planner prompt structure
# ---------------------------------------------------------------------------


def test_recommend_best_prompt_structure():
    fi = FramingIntent(mode=FramingMode.RECOMMEND_BEST)
    prompt = build_system_prompt("frame", None, fi, None)
    assert "RECOMMEND BEST MODE" in prompt
    assert "chosen_framing_mode" in prompt
    assert "chosen_framing_why" in prompt
    assert "outpaint_needed" in prompt


def test_specific_mode_prompt_includes_focus_and_ratio():
    fi = FramingIntent(
        mode=FramingMode.PORTRAIT_HEADROOM,
        focus_instruction="Leave breathing room above the head; keep face in upper third.",
        frame_ratio="3:4",
    )
    prompt = build_system_prompt("frame", None, fi, (2250, 3000))
    assert "portrait_headroom" in prompt
    assert "Leave breathing room" in prompt
    assert "3:4" in prompt
    assert "outpaint_needed" in prompt


# ---------------------------------------------------------------------------
# DoD #5 — preferences in RECOMMEND_BEST
# ---------------------------------------------------------------------------


def test_recommend_best_prefs_in_prompt():
    fi = FramingIntent(mode=FramingMode.RECOMMEND_BEST)
    prefs = Preferences(explicit=[ExplicitRule(description="prefer portrait", active=True)])
    prompt = build_system_prompt("frame", prefs, fi, None)
    assert "prefer portrait" in prompt


# ---------------------------------------------------------------------------
# DoD #6 — user instruction appears before preferences
# ---------------------------------------------------------------------------


def test_recommend_best_user_instruction_before_prefs():
    fi = FramingIntent(mode=FramingMode.RECOMMEND_BEST, user_instruction="leave room above head")
    prefs = Preferences(explicit=[ExplicitRule(description="prefer landscape", active=True)])
    prompt = build_system_prompt("frame", prefs, fi, None)
    assert "leave room above head" in prompt
    assert prompt.index("leave room above head") < prompt.index("prefer landscape")


# ---------------------------------------------------------------------------
# DoD #1 — no head-clipping (integration marker)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_portrait_headroom_no_head_clip():
    """Requires ANTHROPIC_API_KEY. Verifies VLM produces non-clipping crop."""
    from pathlib import Path

    import numpy as np

    from vlm_photo_editor.agents.planner import Planner
    from vlm_photo_editor.imageio.container import ImageContainer
    from vlm_photo_editor.planner.compiler import Compiler
    from vlm_photo_editor.schema.ops import OpName

    FACE_TOP_Y = 10  # known top of face in synthetic fixture
    pixels = np.zeros((200, 150, 3), dtype=np.uint8)
    pixels[FACE_TOP_Y:80, 40:110] = 200  # synthetic face region

    container = ImageContainer(
        pixels=pixels,
        bit_depth=8,
        source_path=Path("/fake/face_portrait.jpg"),
    )
    fi = FramingIntent(
        mode=FramingMode.PORTRAIT_HEADROOM,
        focus_instruction=focus_instruction(FramingMode.PORTRAIT_HEADROOM),
        frame_ratio="3:4",
    )
    plan = Planner().plan(container, intent="frame portrait", mode="frame", framing_intent=fi)
    result = Compiler().compile(plan, "frame")
    crop_ops = [op for op in result.op_graph.ops if op.op_name == OpName.CROP]
    if crop_ops:
        op = crop_ops[0]
        top = op.params["top"]
        assert top <= FACE_TOP_Y, "crop clips top of head"
