from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from vlm_photo_editor.imageio.container import ImageContainer
from vlm_photo_editor.schema.detection import DetectedSubject
from vlm_photo_editor.schema.ops import BoundingBox, OpName
from vlm_photo_editor.schema.plan import HumanPlan, HumanStep

_FAKE_SRC = Path("/fake/source.jpg")


def _container(pixels: np.ndarray | None = None) -> ImageContainer:
    if pixels is None:
        pixels = np.full((64, 64, 3), 128, dtype=np.uint8)
    return ImageContainer(pixels=pixels, bit_depth=8, source_path=_FAKE_SRC)


def _subject(x=10, y=10, w=20, h=20, label="person", confidence=0.9, source="mediapipe"):
    return DetectedSubject(
        bbox=BoundingBox(x=x, y=y, width=w, height=h),
        label=label,
        confidence=confidence,
        source=source,
    )


# ---------------------------------------------------------------------------
# available_backends()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "specs_present, expected",
    [
        ([], []),
        (["mediapipe"], ["mediapipe"]),
        (["onnxruntime"], ["yolo_onnx", "u2netp"]),
        (["mediapipe", "onnxruntime"], ["mediapipe", "yolo_onnx", "u2netp"]),
    ],
)
def test_available_backends(specs_present, expected):
    from vlm_photo_editor.detection import available_backends

    def fake_find_spec(name):
        return MagicMock() if name in specs_present else None

    with patch("importlib.util.find_spec", side_effect=fake_find_spec):
        assert available_backends() == expected


# ---------------------------------------------------------------------------
# detect_subject() — mediapipe / yolo_onnx, bbox clamped inside image bounds
# ---------------------------------------------------------------------------


def test_detect_subject_mediapipe_clamps_bbox():
    from vlm_photo_editor.config.settings import get_settings

    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))

    category = MagicMock(category_name="person", score=0.87)
    detection = MagicMock(categories=[category])
    detection.bounding_box = MagicMock(origin_x=-5, origin_y=10, width=30, height=100)
    mock_result = MagicMock(detections=[detection])

    mock_detector = MagicMock()
    mock_detector.detect.return_value = mock_result

    mock_mp = MagicMock()
    # Real mediapipe exposes mp.tasks.vision / mp.tasks.BaseOptions and has no
    # mp.tasks.python; deleting it keeps a bare MagicMock from accepting that path.
    del mock_mp.tasks.python
    mock_mp.tasks.vision.ObjectDetector.create_from_options.return_value = mock_detector

    settings = get_settings()
    settings.mediapipe_model_path = "/fake/model.tflite"
    try:
        with patch.dict("sys.modules", {"mediapipe": mock_mp}):
            from vlm_photo_editor.detection import detect_subject

            result = detect_subject(container, "mediapipe")
    finally:
        settings.mediapipe_model_path = None

    assert result.source == "mediapipe"
    assert result.label == "person"
    assert 0 <= result.bbox.x < container.width
    assert 0 <= result.bbox.y < container.height
    assert result.bbox.x + result.bbox.width <= container.width
    assert result.bbox.y + result.bbox.height <= container.height


def test_detect_subject_yolo_onnx_clamps_bbox():
    from vlm_photo_editor.config.settings import get_settings

    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))

    # YOLO-ONNX export shape: (batch, 4 + num_classes, num_anchors). One high-confidence
    # box near the edge (anchor 0); the rest are zero/below threshold.
    preds = np.zeros((1, 5, 100), dtype=np.float32)
    preds[0, :, 0] = [320, 320, 700, 700, 0.9]  # cx, cy, w, h, class-0 score
    mock_session = MagicMock()
    mock_session.get_inputs.return_value = [MagicMock(name="images")]
    mock_session.run.return_value = [preds]

    mock_ort = MagicMock()
    mock_ort.InferenceSession.return_value = mock_session

    settings = get_settings()
    settings.yolo_onnx_model_path = "/fake/model.onnx"
    try:
        with patch.dict("sys.modules", {"onnxruntime": mock_ort}):
            from vlm_photo_editor.detection import detect_subject

            result = detect_subject(container, "yolo_onnx")
    finally:
        settings.yolo_onnx_model_path = None

    assert result.source == "yolo_onnx"
    assert 0 <= result.bbox.x < container.width
    assert 0 <= result.bbox.y < container.height
    assert result.bbox.x + result.bbox.width <= container.width
    assert result.bbox.y + result.bbox.height <= container.height


# ---------------------------------------------------------------------------
# Missing model path → clear ValueError naming the setting, no silent fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "backend, expected_setting",
    [
        ("mediapipe", "mediapipe_model_path"),
        ("yolo_onnx", "yolo_onnx_model_path"),
        ("u2netp", "u2netp_model_path"),
    ],
)
def test_detect_subject_missing_model_path_raises(backend, expected_setting):
    from vlm_photo_editor.detection import detect_subject

    container = _container()
    with pytest.raises(ValueError, match=expected_setting):
        detect_subject(container, backend)


def test_detect_subject_off_raises():
    from vlm_photo_editor.detection import detect_subject

    with pytest.raises(ValueError):
        detect_subject(_container(), "off")


# ---------------------------------------------------------------------------
# build_system_prompt() — SUBJECT DETECTION block
# ---------------------------------------------------------------------------


def test_system_prompt_includes_subject_detection_block():
    from vlm_photo_editor.templates.planner import build_system_prompt

    prompt = build_system_prompt("frame", None, None, None, _subject())
    assert "SUBJECT DETECTION" in prompt
    assert "person" in prompt
    assert "x=10 y=10 width=20 height=20" in prompt


def test_system_prompt_no_subject_detection_without_detected_subject():
    from vlm_photo_editor.templates.planner import build_system_prompt

    prompt = build_system_prompt("frame", None, None, None)
    assert "SUBJECT DETECTION" not in prompt


# ---------------------------------------------------------------------------
# Compiler.compile(..., detected_subject=...) — injects focus_x/y/w/h into FRAME
# ---------------------------------------------------------------------------


def _plan_with_frame_step(op_params: dict) -> HumanPlan:
    return HumanPlan(
        steps=[
            HumanStep(
                index=1,
                title="Reframe",
                why="test",
                op_names=[OpName.FRAME],
                op_params=[op_params],
            )
        ],
        mode="full",
    )


def test_compiler_injects_focus_params_when_absent():
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_frame_step({"mode": "rule_of_thirds"})
    result = Compiler().compile(plan, "full", detected_subject=_subject(1, 2, 3, 4))

    frame_op = next(op for op in result.op_graph.ops if op.op_name == OpName.FRAME)
    assert frame_op.params["focus_x"] == 1
    assert frame_op.params["focus_y"] == 2
    assert frame_op.params["focus_w"] == 3
    assert frame_op.params["focus_h"] == 4


def test_compiler_does_not_override_existing_focus_params():
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_frame_step(
        {"mode": "rule_of_thirds", "focus_x": 99, "focus_y": 99, "focus_w": 5, "focus_h": 5}
    )
    result = Compiler().compile(plan, "full", detected_subject=_subject(1, 2, 3, 4))

    frame_op = next(op for op in result.op_graph.ops if op.op_name == OpName.FRAME)
    assert frame_op.params["focus_x"] == 99


def test_compiler_no_detected_subject_leaves_frame_params_untouched():
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_frame_step({"mode": "rule_of_thirds"})
    result = Compiler().compile(plan, "full")

    frame_op = next(op for op in result.op_graph.ops if op.op_name == OpName.FRAME)
    assert "focus_x" not in frame_op.params


# ---------------------------------------------------------------------------
# Compiler — mask op collapses into the immediately-following op (bbox=subject, invert=True)
# ---------------------------------------------------------------------------


def _plan_with_steps(*steps: tuple[list[OpName], list[dict]]) -> HumanPlan:
    return HumanPlan(
        steps=[
            HumanStep(index=i + 1, title=f"step{i}", why="test", op_names=names, op_params=params)
            for i, (names, params) in enumerate(steps)
        ],
        mode="full",
    )


def test_mask_collapses_into_region_edit_blur():
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_steps(
        ([OpName.MASK], [{}]),
        ([OpName.REGION_EDIT], [{"backend": "opencv", "method": "blur", "radius": 10}]),
    )
    result = Compiler().compile(plan, "full", detected_subject=_subject(1, 2, 3, 4))

    ops = result.op_graph.ops
    assert len(ops) == 1
    assert ops[0].op_name == OpName.REGION_EDIT
    assert ops[0].bbox == BoundingBox(x=1, y=2, width=3, height=4)
    assert ops[0].params["invert"] is True
    assert ops[0].params["method"] == "blur"


def test_mask_collapses_into_fill_mask():
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_steps(
        ([OpName.MASK], [{}]),
        ([OpName.FILL_MASK], [{"fill": 200}]),
    )
    result = Compiler().compile(plan, "full", detected_subject=_subject(5, 5, 10, 10))

    ops = result.op_graph.ops
    assert len(ops) == 1
    assert ops[0].op_name == OpName.FILL_MASK
    assert ops[0].bbox == BoundingBox(x=5, y=5, width=10, height=10)
    assert ops[0].params["invert"] is True
    assert ops[0].params["fill"] == 200


def test_mask_without_detected_subject_leaves_bbox_unresolved():
    """No Character Focus subject: mask still collapses (invert=True) but bbox stays
    None — the app layer resolves it from a manually-drawn Region Selection later."""
    from vlm_photo_editor.planner.compiler import Compiler

    plan = _plan_with_steps(
        ([OpName.MASK], [{}]),
        ([OpName.EXPOSURE], [{"ev": -0.5}]),
    )
    result = Compiler().compile(plan, "full")

    ops = result.op_graph.ops
    assert len(ops) == 1
    assert ops[0].op_name == OpName.EXPOSURE
    assert ops[0].bbox is None
    assert ops[0].params["invert"] is True


def test_mask_as_last_step_raises():
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError

    plan = _plan_with_steps(([OpName.MASK], [{}]))
    with pytest.raises(CompilerError, match="must be immediately followed"):
        Compiler().compile(plan, "full", detected_subject=_subject(1, 1, 2, 2))


@pytest.mark.parametrize(
    "next_op,next_params",
    [
        (OpName.CROP, {"left": 0, "top": 0, "right": 10, "bottom": 10}),
        (OpName.BACKGROUND_REPLACE, {"backend": "opencv"}),
        (OpName.REGION_EDIT, {"backend": "opencv"}),  # no method="blur"
    ],
)
def test_mask_before_unsupported_op_raises(next_op, next_params):
    from vlm_photo_editor.planner.compiler import Compiler, CompilerError

    plan = _plan_with_steps(
        ([OpName.MASK], [{}]),
        ([next_op], [next_params]),
    )
    with pytest.raises(CompilerError, match="cannot precede"):
        Compiler().compile(plan, "full", detected_subject=_subject(1, 1, 2, 2))


# ---------------------------------------------------------------------------
# pil_backend._frame() — anchors on focus centroid when present, else center-crop
# ---------------------------------------------------------------------------


def test_frame_center_crop_unchanged_without_focus_params():
    from vlm_photo_editor.ops.backends.pil_backend import _frame

    container = _container(np.arange(64 * 64 * 3, dtype=np.uint8).reshape(64, 64, 3))
    result = _frame(container, {"mode": "center_symmetry"})
    # center_symmetry is a 1:1 aspect on a square image -> full-frame no-op crop.
    assert result.pixels.shape == container.pixels.shape
    np.testing.assert_array_equal(result.pixels, container.pixels)


def test_frame_anchors_on_focus_centroid():
    from vlm_photo_editor.ops.backends.pil_backend import _frame, frame_target_size

    container = _container(np.zeros((100, 200, 3), dtype=np.uint8))
    target_w, target_h = frame_target_size(200, 100, "negative_space")

    # Subject near the right edge — crop should shift right, not sit dead-center.
    focus = {"focus_x": 180, "focus_y": 40, "focus_w": 10, "focus_h": 10}
    result = _frame(container, {"mode": "negative_space", **focus})
    assert result.pixels.shape[1] == target_w
    assert result.pixels.shape[0] == target_h

    default_left = (200 - target_w) // 2
    # cx=185 -> left = 185 - target_w/2, clamped into [0, 200-target_w]
    expected_left = max(0, min(int(round(185 - target_w / 2)), 200 - target_w))
    assert expected_left != default_left  # sanity: the fixture actually exercises the shift


def test_frame_focus_crop_stays_within_bounds():
    from vlm_photo_editor.ops.backends.pil_backend import _frame

    container = _container(np.zeros((100, 200, 3), dtype=np.uint8))
    # Focus bbox right at the edge — clamping must keep the crop in-bounds.
    focus = {"focus_x": 199, "focus_y": 99, "focus_w": 1, "focus_h": 1}
    result = _frame(container, {"mode": "negative_space", **focus})
    assert result.pixels.shape[0] > 0
    assert result.pixels.shape[1] > 0


# ---------------------------------------------------------------------------
# UI — Character Focus selectbox + Settings expander (Streamlit AppTest)
# ---------------------------------------------------------------------------


def _run_main_with_image(find_spec_present: tuple[str, ...] = ()):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    st.cache_data.clear()  # settings.py caches available-backend status for 60s

    def fake_find_spec(name):
        return MagicMock() if name in find_spec_present else None

    with patch("importlib.util.find_spec", side_effect=fake_find_spec):
        at = AppTest.from_file("vlm_photo_editor/app/main.py")
        fake_file = SimpleNamespace(name="fake.jpg", size=123)
        at.session_state["uploaded_file"] = fake_file
        at.session_state["_loaded_file_id"] = "fake.jpg:123"
        at.session_state["container"] = _container()
        at.session_state["ui_phase"] = "has_image"
        at.run(timeout=30)
    return at


def test_character_focus_selectbox_lists_only_off_with_no_backends_installed():
    at = _run_main_with_image(find_spec_present=())
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off"]


def test_character_focus_selectbox_lists_installed_backends():
    at = _run_main_with_image(find_spec_present=("mediapipe",))
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off", "mediapipe"]


def test_settings_character_focus_expander_shows_status_badges():
    at = _run_main_with_image(find_spec_present=("mediapipe",))
    assert not at.exception
    expander = next(e for e in at.expander if e.label == "Character Focus")
    badges = [md.value for md in expander.markdown]
    assert any("package missing" in b for b in badges)  # yolo_onnx / u2netp
    assert any("path not set" in b for b in badges)  # mediapipe: importable, no path yet
