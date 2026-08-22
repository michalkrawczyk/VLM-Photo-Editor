import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from vlm_photo_editor.schema.ops import (
    Backend,
    BoundingBox,
    Op,
    OpGraph,
    OpName,
    RiskTier,
)
from vlm_photo_editor.schema.plan import CompilerResult, HumanPlan, HumanStep
from vlm_photo_editor.schema.prefs import ExplicitRule, LearnedRule, Preferences
from vlm_photo_editor.schema.recipe import GenAIOp, Recipe

FIXTURES = Path("tests/fixtures/schemas")


def test_opgraph_fixture():
    data = json.loads((FIXTURES / "sample_opgraph.json").read_text())
    graph = OpGraph.model_validate(data)
    assert len(graph.ops) == 2
    assert graph.ops[0].op_name == OpName.CROP
    assert graph.ops[0].step_id == "step-001"
    assert graph.ops[1].op_name == OpName.EXPOSURE


def test_plan_fixture():
    data = json.loads((FIXTURES / "sample_plan.json").read_text())
    plan = HumanPlan.model_validate(data)
    assert len(plan.steps) == 2
    assert plan.steps[0].step_id == "00000000-0000-0000-0000-000000000001"
    assert plan.steps[0].title == "Crop to 4:3"
    assert plan.steps[1].step_id == "00000000-0000-0000-0000-000000000002"


def test_recipe_fixture():
    data = json.loads((FIXTURES / "sample_recipe.json").read_text())
    recipe = Recipe.model_validate(data)
    assert recipe.source_path == "tests/fixtures/images/sample.jpg"
    assert len(recipe.op_graph.ops) == 1
    assert recipe.op_graph.ops[0].op_name == OpName.CROP
    assert recipe.genai_ops == []


@pytest.mark.parametrize(
    "op_name,params",
    [
        (OpName.CROP, {"left": 0, "top": 0, "right": 100, "bottom": 100}),
        (OpName.EXPOSURE, {"ev": 1.0}),
        (OpName.ROTATE, {"angle": 90}),
        (OpName.WHITE_BALANCE, {"temperature": 5500}),
    ],
)
def test_op_round_trip(op_name: OpName, params: dict) -> None:
    op = Op(op_name=op_name, params=params, step_id="test-step")
    restored = Op.model_validate(op.model_dump())
    assert restored.op_name == op_name
    assert restored.params == params
    assert restored.step_id == "test-step"


def test_op_with_bbox():
    op = Op(
        op_name=OpName.REGION_EDIT,
        params={"prompt": "blurred bokeh"},
        bbox=BoundingBox(x=10, y=20, width=300, height=200),
        risk_tier=RiskTier.HIGH,
        step_id="step-bbox",
    )
    restored = Op.model_validate(op.model_dump())
    assert restored.bbox is not None
    assert restored.bbox.width == 300
    assert restored.risk_tier == RiskTier.HIGH


def test_bounding_box_rejects_zero_dimension():
    with pytest.raises(Exception):
        BoundingBox(x=0, y=0, width=0, height=100)
    with pytest.raises(Exception):
        BoundingBox(x=0, y=0, width=100, height=0)


def test_bounding_box_rejects_negative_origin():
    with pytest.raises(Exception):
        BoundingBox(x=-1, y=0, width=100, height=100)


def test_compiler_result_round_trip():
    _sid = "00000000-0000-0000-0000-000000000001"
    plan = HumanPlan(
        steps=[HumanStep(step_id=_sid, index=1, title="Crop", why="Better composition")]
    )
    graph = OpGraph(
        ops=[
            Op(
                op_name=OpName.CROP,
                params={"left": 0, "top": 0, "right": 400, "bottom": 300},
                step_id=_sid,
            )
        ]
    )
    result = CompilerResult(plan=plan, op_graph=graph)
    restored = CompilerResult.model_validate(result.model_dump())
    assert restored.plan.steps[0].step_id == _sid
    assert restored.op_graph.ops[0].op_name == OpName.CROP


def test_genai_op_stored_without_key():
    op = GenAIOp(
        step_id="s1", model="stable-diffusion-inpainting", prompt="forest background", seed=42
    )
    data = op.model_dump()
    assert "api_key" not in data
    assert data["model"] == "stable-diffusion-inpainting"
    assert data["seed"] == 42


def test_preferences_round_trip():
    prefs = Preferences(
        explicit=[ExplicitRule(description="prefer warm tones")],
        learned=[LearnedRule(description="user often increases exposure", confidence=0.8)],
    )
    restored = Preferences.model_validate(prefs.model_dump())
    assert len(restored.explicit) == 1
    assert len(restored.learned) == 1
    assert restored.learned[0].confidence == 0.8
    assert restored.learned[0].approved is False


def test_learned_rule_confidence_bounds():
    with pytest.raises(Exception):
        LearnedRule(description="test", confidence=1.5)
    with pytest.raises(Exception):
        LearnedRule(description="test", confidence=-0.1)


def test_explicit_rule_overrides_by_priority():
    explicit = ExplicitRule(description="warm tones", active=True)
    learned = LearnedRule(description="cool tones", active=True, approved=True)
    prefs = Preferences(explicit=[explicit], learned=[learned])
    assert prefs.explicit[0].description == "warm tones"
    assert prefs.learned[0].description == "cool tones"


# ---------------------------------------------------------------------------
# S-D1 — BatchImageRecord.filename path-traversal sanitisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("normal.jpg", "normal.jpg"),
        ("../etc/passwd", "passwd"),
        ("/absolute/path/file.jpg", "file.jpg"),
        ("subdir/image.png", "image.png"),
    ],
)
def test_batch_filename_sanitisation(raw: str, expected: str) -> None:
    from vlm_photo_editor.schema.batch import BatchImageRecord

    record = BatchImageRecord(filename=raw)
    assert record.filename == expected


def test_batch_filename_rejects_null_bytes() -> None:
    from pydantic import ValidationError

    from vlm_photo_editor.schema.batch import BatchImageRecord

    with pytest.raises((ValueError, ValidationError)):
        BatchImageRecord(filename="evil\x00file.jpg")


# ---------------------------------------------------------------------------
# S-B2 — schema __init__ exports AcceptMode, FramingIntent, EditDelta
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# PLN-B6 — step_id must be a valid UUID string
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "s1",
        "step-001",
        "not-a-uuid",
        "123",
        "c2f5e813-22b4-5d9g-0f7e-3g4b1d6c8e90",  # VLM hallucination pattern
    ],
)
def test_human_step_rejects_non_uuid_step_id(bad_id: str) -> None:
    with pytest.raises(ValidationError, match="not a valid UUID"):
        HumanStep(step_id=bad_id, index=1, title="t", why="w")


def test_human_step_accepts_valid_uuid_step_id() -> None:
    import uuid

    sid = str(uuid.uuid4())
    step = HumanStep(step_id=sid, index=1, title="t", why="w")
    assert step.step_id == sid


def test_human_step_default_step_id_is_valid_uuid() -> None:
    step = HumanStep(index=1, title="t", why="w")
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        step.step_id,
        re.IGNORECASE,
    )


def test_schema_init_exports() -> None:
    import vlm_photo_editor.schema as schema
    from vlm_photo_editor.schema import AcceptMode, EditDelta, FramingIntent  # noqa: F401

    assert "AcceptMode" in schema.__all__
    assert "FramingIntent" in schema.__all__
    assert "EditDelta" in schema.__all__
