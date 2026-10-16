from __future__ import annotations

from pathlib import Path

import pytest

from vlm_photo_editor.schema.op_catalog import BBoxClass, OpSpec, all_specs, get_spec, register_op
from vlm_photo_editor.schema.ops import Backend, OpName, RiskTier
from vlm_photo_editor.templates.planner import build_system_prompt

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_catalog_covers_every_opname():
    assert set(OpName) == set(all_specs().keys())


def test_register_op_rejects_duplicate():
    with pytest.raises(ValueError, match="already registered"):
        register_op(
            OpSpec(
                op_name=OpName.CROP,
                required_params=(),
                risk_tier=RiskTier.LOW,
                default_backend=Backend.PIL,
                bbox_class=BBoxClass.GENERIC_CONFINABLE,
                ps_expressible=True,
                doc_lines=(),
            )
        )


def test_register_op_replace_allows_overwrite():
    original = get_spec(OpName.CROP)
    try:
        register_op(
            OpSpec(
                op_name=OpName.CROP,
                required_params=(),
                risk_tier=RiskTier.LOW,
                default_backend=Backend.PIL,
                bbox_class=BBoxClass.GENERIC_CONFINABLE,
                ps_expressible=True,
                doc_lines=(),
            ),
            replace=True,
        )
        assert get_spec(OpName.CROP).required_params == ()
    finally:
        register_op(original, replace=True)


def test_get_spec_missing_raises_keyerror():
    with pytest.raises(KeyError):
        get_spec("not_a_real_op")  # type: ignore[arg-type]


@pytest.mark.parametrize("op_name", list(OpName))
def test_optional_params_is_tuple_disjoint_from_required(op_name):
    spec = get_spec(op_name)
    assert isinstance(spec.optional_params, tuple)
    assert not (set(spec.required_params) & set(spec.optional_params))


@pytest.mark.parametrize(
    "op_name,ps_expressible,bbox_class",
    [
        (OpName.CROP, True, BBoxClass.SIZE_CHANGING),
        (OpName.ROTATE, True, BBoxClass.SIZE_CHANGING),
        (OpName.FRAME, False, BBoxClass.SIZE_CHANGING),
        (OpName.REGION_EDIT, True, BBoxClass.SELF_MANAGED_INPAINT),
        (OpName.BACKGROUND_REPLACE, False, BBoxClass.SELF_MANAGED_INPAINT),
        (OpName.WHITE_BALANCE, True, BBoxClass.GENERIC_CONFINABLE),
        (OpName.TONE, True, BBoxClass.GENERIC_CONFINABLE),
        (OpName.SATURATION, True, BBoxClass.GENERIC_CONFINABLE),
        (OpName.SHARPEN, True, BBoxClass.GENERIC_CONFINABLE),
    ],
)
def test_spec_field_spot_checks(op_name, ps_expressible, bbox_class):
    spec = get_spec(op_name)
    assert spec.ps_expressible is ps_expressible
    assert spec.bbox_class is bbox_class


@pytest.mark.parametrize(
    "op_name,required_params,risk_tier,default_backend",
    [
        (OpName.CROP, ("left", "top", "right", "bottom"), RiskTier.LOW, Backend.PIL),
        (OpName.ROTATE, ("angle",), RiskTier.LOW, Backend.PIL),
        (OpName.WHITE_BALANCE, ("temperature",), RiskTier.LOW, Backend.PIL),
        (OpName.EXPOSURE, ("ev",), RiskTier.LOW, Backend.PIL),
        (OpName.DENOISE, (), RiskTier.LOW, Backend.PIL),
        (OpName.MASK, (), RiskTier.MEDIUM, Backend.PIL),
        (OpName.FILL_MASK, (), RiskTier.MEDIUM, Backend.PIL),
        (OpName.REGION_EDIT, ("prompt",), RiskTier.HIGH, Backend.GENAI),
        (OpName.BACKGROUND_REPLACE, ("prompt",), RiskTier.HIGH, Backend.GENAI),
        (OpName.FRAME, ("mode",), RiskTier.LOW, Backend.PIL),
    ],
)
def test_spec_matches_ported_values(op_name, required_params, risk_tier, default_backend):
    spec = get_spec(op_name)
    assert spec.required_params == required_params
    assert spec.risk_tier == risk_tier
    assert spec.default_backend == default_backend


def test_render_doc_returns_list_copy_of_doc_lines():
    spec = get_spec(OpName.MASK)
    doc = spec.render_doc()
    assert doc == list(spec.doc_lines)
    assert len(doc) == 6  # mask's prose block is 6 lines


@pytest.mark.parametrize(
    "op_name,param,present,absent",
    [
        (OpName.FRAME, "mode", "rule_of_thirds", "bogus"),
        (OpName.REGION_EDIT, "method", "blur", "biharmonic"),
    ],
)
def test_enum_params_declared(op_name, param, present, absent):
    """SC-B1: FRAME.mode and REGION_EDIT.method carry an allowed-value set."""
    choices = dict(get_spec(op_name).enum_params)
    assert param in choices
    assert present in choices[param]
    assert absent not in choices[param]


def test_enum_params_default_empty_for_numeric_ops():
    assert get_spec(OpName.EXPOSURE).enum_params == ()


def test_system_prompt_byte_identical_to_pre_catalog_baseline():
    """Guards against silent prompt-wording drift from the doc_lines port into the
    catalog. Baseline captured from build_system_prompt("full", None, None, None)
    before templates/planner.py was refactored to read from op_catalog."""
    baseline = (_FIXTURES / "prompts" / "base_prompt_full_mode.txt").read_text()
    assert build_system_prompt("full", None, None, None) == baseline
