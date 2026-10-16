from __future__ import annotations

import tempfile
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
# ready_backends() — package importable AND model path resolves
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "specs_present, paths, expected",
    [
        # importable but no path -> not ready
        (["mediapipe", "onnxruntime"], {}, []),
        # path set only for the ones whose package is also importable
        (["mediapipe"], {"mediapipe_model_path": "/m.tflite"}, ["mediapipe"]),
        (
            # yolo_onnx path set but no sibling classes.txt -> not ready
            # (see test_ready_backends_yolo_requires_classes_txt for the ready case)
            ["mediapipe", "onnxruntime"],
            {"mediapipe_model_path": "/m", "yolo_onnx_model_path": "/y", "u2netp_model_path": "/u"},
            ["mediapipe", "u2netp"],
        ),
        # path set but package missing -> still not ready
        ([], {"yolo_onnx_model_path": "/y.onnx"}, []),
    ],
)
def test_ready_backends(specs_present, paths, expected):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import ready_backends

    def fake_find_spec(name):
        return MagicMock() if name in specs_present else None

    settings = get_settings()
    saved = {
        attr: getattr(settings, attr)
        for attr in ("mediapipe_model_path", "yolo_onnx_model_path", "u2netp_model_path")
    }
    for attr in saved:
        setattr(settings, attr, paths.get(attr))
    try:
        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            assert ready_backends() == expected
    finally:
        for attr, value in saved.items():
            setattr(settings, attr, value)


def _yolo_bundle(tmp_path: Path, classes: tuple[str, ...] | None = ("person",)) -> str:
    """Write a dummy .onnx + optional sibling classes.txt; return the model path."""
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    if classes is not None:
        (tmp_path / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    return str(model)


@pytest.mark.parametrize(
    "classes, ready",
    [
        (("person", "bicycle"), True),
        (("Human",), True),
        (("dog", "cat"), True),  # no person class is allowed (UI warns instead)
        (None, False),  # no classes.txt at all
    ],
)
def test_ready_backends_yolo_requires_classes_txt(tmp_path, classes, ready):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import ready_backends

    model_path = _yolo_bundle(tmp_path, classes)
    settings = get_settings()
    attrs = ("mediapipe_model_path", "yolo_onnx_model_path", "u2netp_model_path")
    saved = {a: getattr(settings, a) for a in attrs}
    settings.mediapipe_model_path = None
    settings.u2netp_model_path = None
    settings.yolo_onnx_model_path = model_path
    try:
        with patch(
            "importlib.util.find_spec",
            side_effect=lambda n: MagicMock() if n == "onnxruntime" else None,
        ):
            assert ("yolo_onnx" in ready_backends()) is ready
    finally:
        for a, v in saved.items():
            setattr(settings, a, v)


# ---------------------------------------------------------------------------
# classes.txt parsing helpers
# ---------------------------------------------------------------------------


def test_load_class_labels_keeps_interior_blanks(tmp_path):
    from vlm_photo_editor.detection._common import load_class_labels

    (tmp_path / "classes.txt").write_text("person\n\nbicycle\n", encoding="utf-8")
    assert load_class_labels(tmp_path / "model.onnx") == ["person", "", "bicycle"]


def test_load_class_labels_missing_file_raises(tmp_path):
    from vlm_photo_editor.detection._common import load_class_labels

    with pytest.raises(ValueError, match="classes.txt"):
        load_class_labels(tmp_path / "model.onnx")


@pytest.mark.parametrize("contents", ["", "   \n\n"])
def test_load_class_labels_no_names_raises(tmp_path, contents):
    from vlm_photo_editor.detection._common import load_class_labels

    (tmp_path / "classes.txt").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="classes.txt"):
        load_class_labels(tmp_path / "model.onnx")


@pytest.mark.parametrize(
    "labels, expected",
    [
        (["person"], True),
        (["Human"], True),
        ([" PERSON "], True),
        (["dog", "cat"], False),
        ([], False),
    ],
)
def test_has_human_label(labels, expected):
    from vlm_photo_editor.detection._common import has_human_label

    assert has_human_label(labels) is expected


# ---------------------------------------------------------------------------
# detector_labels() / detector_has_label() — vocabulary introspection
# ---------------------------------------------------------------------------


def test_detector_labels_and_has_label_for_yolo_onnx(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detector_has_label, detector_labels

    model_path = _yolo_bundle(tmp_path, ("person", "face"))
    settings = get_settings()
    saved = settings.yolo_onnx_model_path
    settings.yolo_onnx_model_path = model_path
    try:
        assert detector_labels("yolo_onnx") == ["person", "face"]
        assert detector_has_label("yolo_onnx", "face") is True
        assert detector_has_label("yolo_onnx", "FACE") is True
        assert detector_has_label("yolo_onnx", "bicycle") is False
    finally:
        settings.yolo_onnx_model_path = saved


@pytest.mark.parametrize("backend", ["u2netp", "off", "bogus"])
def test_detector_labels_none_for_non_classes_backends(backend):
    from vlm_photo_editor.detection import detector_has_label, detector_labels

    assert detector_labels(backend) is None
    assert detector_has_label(backend, "face") is False


# ---------------------------------------------------------------------------
# _path_setting() — env var > .env > bundled default > None
# ---------------------------------------------------------------------------


def test_path_setting_env_var_wins(monkeypatch, tmp_path):
    from vlm_photo_editor.config.settings import _path_setting

    bundled = tmp_path / "bundled.onnx"
    bundled.write_bytes(b"x")
    monkeypatch.setenv("VLM_TEST_MODEL_PATH", "/from/env")
    assert _path_setting("VLM_TEST_MODEL_PATH", bundled) == "/from/env"


def test_path_setting_reads_dotenv_when_env_unset(monkeypatch, tmp_path):
    from vlm_photo_editor.config.settings import _path_setting

    monkeypatch.delenv("VLM_TEST_MODEL_PATH", raising=False)
    (tmp_path / ".env").write_text("VLM_TEST_MODEL_PATH=/from/dotenv\n")
    monkeypatch.chdir(tmp_path)
    assert _path_setting("VLM_TEST_MODEL_PATH") == "/from/dotenv"


def test_path_setting_bundled_default_only_when_file_exists(monkeypatch, tmp_path):
    from vlm_photo_editor.config.settings import _path_setting

    monkeypatch.delenv("VLM_TEST_MODEL_PATH", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    assert _path_setting("VLM_TEST_MODEL_PATH", tmp_path / "missing.onnx") is None
    present = tmp_path / "present.onnx"
    present.write_bytes(b"x")
    assert _path_setting("VLM_TEST_MODEL_PATH", present) == str(present)


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


def _mock_session(preds: np.ndarray) -> MagicMock:
    """A stand-in for onnxruntime.InferenceSession(...) that returns *preds*.

    Patch ``onnxruntime.InferenceSession`` with this rather than swapping the whole
    module via ``sys.modules`` — clearing ``sys.modules`` in a ``patch.dict`` teardown
    wipes opencv's lazily-registered ``cv2.dnn`` symbols for later tests.
    """
    session = MagicMock()
    session.get_inputs.return_value = [MagicMock(name="images")]
    session.run.return_value = [preds]
    return session


def test_detect_subject_yolo_onnx_clamps_bbox(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))

    # YOLO-ONNX export shape: (batch, 4 + num_classes, num_anchors). One high-confidence
    # box near the edge (anchor 0); the rest are zero/below threshold. 1 class -> the
    # sibling classes.txt must name exactly 1 class.
    preds = np.zeros((1, 5, 100), dtype=np.float32)
    preds[0, :, 0] = [320, 320, 700, 700, 0.9]  # cx, cy, w, h, class-0 score
    model_path = _yolo_bundle(tmp_path, ("person",))

    settings = get_settings()
    settings.yolo_onnx_model_path = model_path
    try:
        with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
            result = detect_subject(container, "yolo_onnx")
    finally:
        settings.yolo_onnx_model_path = None

    assert result.source == "yolo_onnx"
    assert result.label == "person"  # from the sibling classes.txt
    assert 0 <= result.bbox.x < container.width
    assert 0 <= result.bbox.y < container.height
    assert result.bbox.x + result.bbox.width <= container.width
    assert result.bbox.y + result.bbox.height <= container.height


def test_yolo_onnx_detect_sets_label_from_classes_txt(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))
    # 2 classes; anchor 0 scores highest on class 1.
    preds = np.zeros((1, 6, 100), dtype=np.float32)
    preds[0, :, 0] = [320, 320, 80, 80, 0.1, 0.9]
    model_path = _yolo_bundle(tmp_path, ("person", "bicycle"))

    settings = get_settings()
    settings.yolo_onnx_model_path = model_path
    try:
        with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
            result = detect_subject(container, "yolo_onnx")
    finally:
        settings.yolo_onnx_model_path = None

    assert result.label == "bicycle"


def test_yolo_onnx_detect_raises_without_classes_txt(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    model_path = _yolo_bundle(tmp_path, classes=None)  # .onnx only, no classes.txt
    settings = get_settings()
    settings.yolo_onnx_model_path = model_path
    try:
        with pytest.raises(ValueError, match="classes.txt"):
            detect_subject(_container(), "yolo_onnx")
    finally:
        settings.yolo_onnx_model_path = None


def test_yolo_onnx_detect_works_without_person_class(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    preds = np.zeros((1, 6, 100), dtype=np.float32)
    preds[0, :, 0] = [320, 320, 80, 80, 0.1, 0.9]
    model_path = _yolo_bundle(tmp_path, ("cat", "dog"))
    settings = get_settings()
    settings.yolo_onnx_model_path = model_path
    try:
        with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
            assert detect_subject(_container(), "yolo_onnx").label == "dog"
    finally:
        settings.yolo_onnx_model_path = None


def test_yolo_onnx_detect_raises_on_vocab_size_mismatch(tmp_path):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    preds = np.zeros((1, 5, 100), dtype=np.float32)  # model emits 1 class
    preds[0, :, 0] = [320, 320, 80, 80, 0.9]
    model_path = _yolo_bundle(tmp_path, ("person", "bicycle"))  # classes.txt names 2

    settings = get_settings()
    settings.yolo_onnx_model_path = model_path
    try:
        with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
            with pytest.raises(ValueError, match="classes.txt"):
                detect_subject(_container(), "yolo_onnx")
    finally:
        settings.yolo_onnx_model_path = None


# ---------------------------------------------------------------------------
# DET-P1 — degenerate / low-confidence detections must not define a freeze region
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "box",
    [
        (900, 700, 50, 50),  # entirely off the bottom-right
        (-100, -100, 50, 50),  # entirely off the top-left
        (640, 100, 30, 30),  # flush against the right edge, zero width inside
    ],
)
def test_clamp_bbox_raises_when_box_has_no_overlap(box):
    from vlm_photo_editor.detection._common import clamp_bbox

    x, y, w, h = box
    with pytest.raises(ValueError, match="no overlap"):
        clamp_bbox(x, y, w, h, 640, 480)


def test_clamp_bbox_partial_overlap_still_returns():
    from vlm_photo_editor.detection._common import clamp_bbox

    bbox = clamp_bbox(-20, -20, 60, 60, 640, 480)  # top-left corner overhangs
    assert (bbox.x, bbox.y) == (0, 0)
    assert bbox.width == 40 and bbox.height == 40


def test_detect_subject_drops_below_confidence_floor():
    """DET-P1: a detection scoring below _MIN_CONFIDENCE is not trusted as a subject."""
    from vlm_photo_editor.config.settings import get_settings

    container = _container(np.full((64, 64, 3), 128, dtype=np.uint8))

    detection = MagicMock(categories=[])  # -> backend emits confidence 0.0
    detection.bounding_box = MagicMock(origin_x=5, origin_y=5, width=30, height=30)
    mock_detector = MagicMock()
    mock_detector.detect.return_value = MagicMock(detections=[detection])

    mock_mp = MagicMock()
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

    assert result is None


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
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import detect_subject

    # yolo_onnx_model_path has a bundled default (infer_models/yolo/yolo26s.onnx) that
    # may exist on the dev box — force every backend's path unset for this check.
    settings = get_settings()
    saved = getattr(settings, expected_setting)
    setattr(settings, expected_setting, None)
    container = _container()
    try:
        with pytest.raises(ValueError, match=expected_setting):
            detect_subject(container, backend)
    finally:
        setattr(settings, expected_setting, saved)


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


def _run_main_with_image(
    find_spec_present: tuple[str, ...] = (),
    model_paths: dict[str, str | None] | None = None,
    extra_state: dict[str, object] | None = None,
    scan_dir: Path | None = None,
):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from vlm_photo_editor.config.settings import get_settings

    st.cache_data.clear()  # settings.py caches available-backend status for 60s

    def fake_find_spec(name):
        return MagicMock() if name in find_spec_present else None

    settings = get_settings()
    path_attrs = ("mediapipe_model_path", "yolo_onnx_model_path", "u2netp_model_path")
    scan_attrs = ("detector_models_dir", "detectors_file")
    saved = {attr: getattr(settings, attr) for attr in (*path_attrs, *scan_attrs)}
    # Neutralise the bundled yolo_onnx default and the scanned/user registries so the
    # picker is deterministic; callers opt specific backends back in via model_paths.
    for attr in path_attrs:
        setattr(settings, attr, (model_paths or {}).get(attr))
    empty_dir = Path(tempfile.mkdtemp(prefix="cf_empty_"))
    settings.detector_models_dir = scan_dir or empty_dir
    settings.detectors_file = empty_dir / "detectors.json"

    try:
        with patch("importlib.util.find_spec", side_effect=fake_find_spec):
            at = AppTest.from_file("vlm_photo_editor/app/main.py")
            fake_file = SimpleNamespace(name="fake.jpg", size=123)
            at.session_state["uploaded_file"] = fake_file
            at.session_state["_loaded_file_id"] = "fake.jpg:123"
            at.session_state["container"] = _container()
            at.session_state["ui_phase"] = "has_image"
            for key, value in (extra_state or {}).items():
                at.session_state[key] = value
            at.run(
                timeout=90
            )  # AppTest cold-starts the whole app; 30s is flaky under full-file load
    finally:
        for attr, value in saved.items():
            setattr(settings, attr, value)
    return at


def test_character_focus_selectbox_lists_only_off_with_no_backends_installed():
    at = _run_main_with_image(find_spec_present=())
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off"]


def test_character_focus_selectbox_lists_installed_backend_with_model_path():
    at = _run_main_with_image(
        find_spec_present=("mediapipe",),
        model_paths={"mediapipe_model_path": "/fake/model.tflite"},
    )
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off", "mediapipe"]


def test_character_focus_selectbox_hides_installed_backend_without_model_path():
    at = _run_main_with_image(find_spec_present=("mediapipe",))  # importable, no path
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off"]


def test_generate_plan_surfaces_backend_misconfig_instead_of_crashing(tmp_path):
    """A Character Focus backend that raises must set an error banner, not crash the app.

    Guards the fix that moved the detection call inside ``_do_generate_plan``'s
    ``try`` block. Reframe Only + a preset composition auto-generates on load, so a
    single run drives the whole path; ``detect_subject`` is patched to raise the
    misconfiguration ``ValueError``.
    """
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from vlm_photo_editor.config.settings import get_settings

    st.cache_data.clear()
    settings = get_settings()
    saved = settings.yolo_onnx_model_path
    # Real bundle so ready_backends() keeps yolo_onnx in the picker; the patched
    # detect_subject below is what raises.
    settings.yolo_onnx_model_path = _yolo_bundle(tmp_path, ("person",))

    try:
        with patch(
            "vlm_photo_editor.detection.detect_subject",
            side_effect=ValueError("yolo_onnx_model_path is not set"),
        ):
            at = AppTest.from_file("vlm_photo_editor/app/main.py")
            at.session_state["uploaded_file"] = SimpleNamespace(name="fake.jpg", size=123)
            at.session_state["_loaded_file_id"] = "fake.jpg:123"
            at.session_state["container"] = _container()
            at.session_state["ui_phase"] = "has_image"
            at.session_state["edit_mode"] = "frame"  # Reframe Only -> auto-generates
            at.session_state["framing_mode"] = "rule_of_thirds"
            at.session_state["character_focus"] = "yolo_onnx"
            at.run(timeout=90)
    finally:
        settings.yolo_onnx_model_path = saved

    assert not at.exception  # the ValueError must not escape to module scope
    assert "yolo_onnx_model_path" in (at.session_state["error"] or "")


def test_settings_character_focus_expander_shows_status_badges():
    at = _run_main_with_image(find_spec_present=("mediapipe",))
    assert not at.exception
    expander = next(e for e in at.expander if e.label == "Character Focus")
    badges = [md.value for md in expander.markdown]
    assert any("package missing" in b for b in badges)  # yolo_onnx / u2netp
    assert any("path not set" in b for b in badges)  # mediapipe: importable, no path yet


def test_settings_expander_flags_yolo_onnx_without_classes_txt(tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")  # .onnx present, no sibling classes.txt
    at = _run_main_with_image(
        find_spec_present=("onnxruntime",),
        model_paths={"yolo_onnx_model_path": str(model)},
    )
    assert not at.exception
    expander = next(e for e in at.expander if e.label == "Character Focus")
    badges = [md.value for md in expander.markdown]
    assert any("classes.txt" in b for b in badges)


# ── Composition dropdown — face_only gated on a "face" detector label ────────


def test_composition_hides_face_only_without_face_detector():
    at = _run_main_with_image(find_spec_present=())
    assert not at.exception
    comp = next(sb for sb in at.selectbox if sb.label == "Composition:")
    assert "face_only" not in comp.options
    assert "rule_of_thirds" in comp.options


def test_composition_shows_face_only_with_face_labelled_detector(tmp_path):
    model_path = _yolo_bundle(tmp_path, ("person", "face"))
    at = _run_main_with_image(
        find_spec_present=("onnxruntime",),
        model_paths={"yolo_onnx_model_path": model_path},
        extra_state={"character_focus": "yolo_onnx"},
    )
    assert not at.exception
    comp = next(sb for sb in at.selectbox if sb.label == "Composition:")
    assert "face_only" in comp.options


# ── DET-B3 — install_backend_deps surfaces pip output on failure ────────────


def test_install_backend_deps_returns_captured_output_on_failure():
    from vlm_photo_editor.detection import install_backend_deps

    fake = SimpleNamespace(returncode=1, stdout="", stderr="ERROR: could not find X\n")
    with patch("subprocess.run", return_value=fake) as run:
        ok, output = install_backend_deps("mediapipe")

    assert ok is False
    assert "could not find X" in output
    assert run.call_args.kwargs.get("capture_output") is True
    assert run.call_args.kwargs.get("text") is True


def test_install_backend_deps_ok_on_success():
    from vlm_photo_editor.detection import install_backend_deps

    fake = SimpleNamespace(returncode=0, stdout="Successfully installed\n", stderr="")
    with patch("subprocess.run", return_value=fake):
        ok, _ = install_backend_deps("u2netp")
    assert ok is True


# ── Pluggable models: registry (scan / manual add), targets, layouts, UI ────


@pytest.fixture
def registry_env(tmp_path, monkeypatch):
    """Isolated model registry: empty scan dir + detectors.json under tmp_path, no legacy
    paths, onnxruntime + mediapipe importable. Returns the scan dir."""
    from vlm_photo_editor.config.settings import get_settings

    settings = get_settings()
    scan = tmp_path / "infer_models"
    scan.mkdir()
    monkeypatch.setattr(settings, "detector_models_dir", scan)
    monkeypatch.setattr(settings, "detectors_file", tmp_path / "cfg" / "detectors.json")
    for attr in ("mediapipe_model_path", "yolo_onnx_model_path", "u2netp_model_path"):
        monkeypatch.setattr(settings, attr, None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: MagicMock())
    return scan


def _model_dir(
    scan: Path,
    name: str,
    *,
    model: str = "m.onnx",
    classes: tuple[str, ...] | None = ("person", "car"),
    manifest: dict | None = None,
) -> Path:
    import json

    d = scan / name
    d.mkdir()
    (d / model).write_bytes(b"\x00")
    if classes is not None:
        (d / "classes.txt").write_text("\n".join(classes) + "\n", encoding="utf-8")
    if manifest is not None:
        (d / "model.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d / model


@pytest.mark.parametrize(
    "kwargs, backend, invalid_contains",
    [
        ({}, "yolo_onnx", None),
        ({"classes": None}, "off", "classes.txt"),  # onnx, no classes.txt, no manifest
        ({"classes": None, "manifest": {"backend": "u2netp"}}, "u2netp", None),
        ({"model": "m.tflite", "classes": None}, "mediapipe", None),
        ({"manifest": {"layout": "bogus"}}, "yolo_onnx", "layout"),
        ({"manifest": {"name": "Pets", "layout": "nms"}}, "yolo_onnx", None),
    ],
)
def test_scan_builds_models_from_dropped_in_dirs(registry_env, kwargs, backend, invalid_contains):
    from vlm_photo_editor.detection import get_model, list_models, ready_models

    _model_dir(registry_env, "custom", **kwargs)
    (model,) = [m for m in list_models() if m.origin != "legacy"]
    assert (model.id, model.origin, model.backend.value) == ("custom", "discovered", backend)
    assert get_model("custom") == model
    if invalid_contains is None:
        assert model.invalid_reason is None
        assert [m.id for m in ready_models()] == ["custom"]
    else:
        assert invalid_contains in (model.invalid_reason or "")
        assert ready_models() == []  # listed with a reason, never offered


def test_scan_dedupes_legacy_path_and_lists_classes(registry_env, monkeypatch):
    from vlm_photo_editor.config.settings import get_settings
    from vlm_photo_editor.detection import list_models, model_has_label, model_has_person

    path = _model_dir(registry_env, "yolo", classes=("dog", "Face"))
    monkeypatch.setattr(get_settings(), "yolo_onnx_model_path", str(path))
    ids = [m.id for m in list_models()]
    assert ids.count("yolo_onnx") == 1 and "yolo" not in ids  # same file: legacy slot wins
    assert model_has_label("yolo_onnx", "face") is True
    assert model_has_person("yolo_onnx") is False  # COCO-less custom model: warn, don't block


def test_mediapipe_labels_from_tflite_metadata_zip(registry_env):
    import zipfile

    from vlm_photo_editor.detection import model_labels

    path = _model_dir(registry_env, "mp", model="d.tflite", classes=None)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("labels.txt", "cat\ndog\n")
    assert model_labels("mp") == ["cat", "dog"]


def test_user_added_model_persists_and_removes(registry_env, tmp_path):
    from vlm_photo_editor.detection import add_user_model, list_models, remove_user_model

    path = _model_dir(tmp_path, "elsewhere", classes=("bird",))
    added = add_user_model(str(path), "Birds")
    assert (added.id, added.origin, added.labels) == ("birds", "user", ["bird"])
    assert [m.id for m in list_models() if m.origin == "user"] == ["birds"]  # re-read from disk

    with pytest.raises(ValueError, match="already registered"):
        add_user_model(str(path))
    with pytest.raises(ValueError, match="Unsupported"):
        add_user_model(str(tmp_path / "notes.txt"))
    with pytest.raises(ValueError, match="No user-added"):
        remove_user_model("nope")

    remove_user_model("birds")
    assert [m for m in list_models() if m.origin == "user"] == []


def _yolo_model(path: Path, labels, layout="yolov8", **extra):
    from vlm_photo_editor.schema.detection import DetectorModel

    return DetectorModel(
        id="t",
        display_name="t",
        backend="yolo_onnx",
        path=str(path),
        labels=list(labels),
        origin="user",
        layout=layout,
        **extra,
    )


def _run_yolo(model, preds, targets=None, container=None):
    from vlm_photo_editor.detection import yolo_onnx_backend

    with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
        return yolo_onnx_backend.detect(container or _container(), model, targets)


def test_yolo_targets_pick_lower_scoring_target_over_higher_scoring_other(tmp_path):
    # 3 classes; anchor 0 = dog @0.9, anchor 1 = person @0.4. Targets restrict the argmax.
    preds = np.zeros((1, 7, 100), dtype=np.float32)
    preds[0, :, 0] = [100, 100, 40, 40, 0.0, 0.9, 0.0]
    preds[0, :, 1] = [500, 500, 40, 40, 0.4, 0.0, 0.0]
    model = _yolo_model(tmp_path / "m.onnx", ("person", "dog", "cat"))
    assert _run_yolo(model, preds).label == "dog"  # default: any class
    assert _run_yolo(model, preds, ["Person"]).label == "person"  # case-insensitive
    assert _run_yolo(model, preds, ["cat"]) is None  # no target above threshold (DET-P2)
    with pytest.raises(ValueError, match="not in this model's classes"):
        _run_yolo(model, preds, ["boat"])


def test_yolo_layout_yolov5_multiplies_objectness(tmp_path):
    # (N, 5+C): anchor 0 has a high class score but ~0 objectness -> filtered out.
    preds = np.zeros((1, 100, 7), dtype=np.float32)
    preds[0, 0] = [320, 320, 80, 80, 0.1, 0.9, 0.0]  # obj 0.1 x 0.9 = 0.09 < threshold
    preds[0, 1] = [320, 320, 80, 80, 0.9, 0.0, 0.8]  # obj 0.9 x 0.8 = 0.72 -> class 1
    model = _yolo_model(tmp_path / "m.onnx", ("a", "b"), layout="yolov5")
    result = _run_yolo(model, preds)
    assert (result.label, round(result.confidence, 2)) == ("b", 0.72)


def test_yolo_layout_nms_rows_and_bad_shape(tmp_path):
    model = _yolo_model(tmp_path / "m.onnx", ("person", "dog"), layout="nms")
    # rows: x1, y1, x2, y2, score, class_id in letterboxed 640px space (64px image -> scale 10)
    preds = np.array([[100, 100, 300, 300, 0.4, 0], [320, 320, 420, 420, 0.9, 1]], np.float32)
    preds = preds[None]  # batch dim, as exported
    assert _run_yolo(model, preds).label == "dog"
    assert _run_yolo(model, preds, ["person"]).label == "person"
    with pytest.raises(ValueError, match="layout"):
        _run_yolo(model, np.zeros((1, 5, 4), np.float32))
    bad_id = np.array([[[0, 0, 10, 10, 0.9, 7]]], np.float32)
    with pytest.raises(ValueError, match="classes.txt"):
        _run_yolo(model, bad_id)


def test_yolo_mismatch_error_names_layout_key(tmp_path):
    preds = np.zeros((1, 5, 100), dtype=np.float32)
    model = _yolo_model(tmp_path / "m.onnx", ("a", "b"))
    with pytest.raises(ValueError, match="layout"):
        _run_yolo(model, preds)


@pytest.mark.parametrize(
    "shape, override, expected",
    [([1, 3, 320, 320], None, 320), ([1, 3, "h", "w"], None, 640), ([1, 3, 320, 320], 1280, 1280)],
)
def test_yolo_input_size_from_onnx_shape_or_override(tmp_path, shape, override, expected):
    from vlm_photo_editor.detection.yolo_onnx_backend import _input_size

    extra = {"input_size": override} if override else {}
    assert _input_size(_yolo_model(tmp_path / "m.onnx", ("a",), **extra), shape) == expected


def test_detect_subject_resolves_scanned_model_and_rejects_bad_targets(registry_env):
    from vlm_photo_editor.detection import detect_subject

    _model_dir(registry_env, "custom", classes=("cat", "dog"))
    preds = np.zeros((1, 6, 100), dtype=np.float32)
    preds[0, :, 0] = [320, 320, 80, 80, 0.1, 0.9]
    with patch("onnxruntime.InferenceSession", return_value=_mock_session(preds)):
        assert detect_subject(_container(), "custom").label == "dog"
        assert detect_subject(_container(), "custom", ["cat"]) is None
    with pytest.raises(ValueError, match="Unknown Character Focus model"):
        detect_subject(_container(), "nope")

    _model_dir(registry_env, "sal", classes=None, manifest={"backend": "u2netp"})
    with pytest.raises(ValueError, match="no enumerable classes"):
        detect_subject(_container(), "sal", ["person"])


def test_detect_subject_invalid_model_raises_its_reason(registry_env):
    from vlm_photo_editor.detection import detect_subject

    _model_dir(registry_env, "bad", classes=None)
    with pytest.raises(ValueError, match="classes.txt"):
        detect_subject(_container(), "bad")


def test_ui_lists_scanned_model_with_classes_and_no_person_warning(tmp_path):
    scan = tmp_path / "infer_models"
    scan.mkdir()
    _model_dir(scan, "pets", classes=("cat", "dog"), manifest={"name": "Pets"})
    at = _run_main_with_image(
        find_spec_present=("onnxruntime",),
        scan_dir=scan,
        extra_state={"character_focus": "pets"},
    )
    assert not at.exception
    cf = next(sb for sb in at.selectbox if sb.label == "Character Focus:")
    assert cf.options == ["off", "Pets (yolo_onnx)"]
    targets = next(m for m in at.multiselect if m.label.startswith("Target classes"))
    assert targets.options == ["cat", "dog"]
    assert any("no person/face class" in w.value for w in at.warning)
    assert not [b for b in at.button if b.label == "Person preset"]


def test_ui_person_model_shows_preset_and_no_warning(tmp_path):
    scan = tmp_path / "infer_models"
    scan.mkdir()
    _model_dir(scan, "coco", classes=("person", "dog"))
    at = _run_main_with_image(
        find_spec_present=("onnxruntime",),
        scan_dir=scan,
        extra_state={"character_focus": "coco"},
    )
    assert not at.exception
    assert not any("no person/face class" in w.value for w in at.warning)
    assert [b for b in at.button if b.label == "Person preset"]


def test_generate_plan_passes_selected_targets_to_detector(registry_env):
    """Auto-generating in Reframe Only mode must hand the picked classes to detect_subject."""
    from streamlit.testing.v1 import AppTest

    _model_dir(registry_env, "coco", classes=("person", "dog"))
    container = _container()
    # Raise so the flow stops at detection instead of reaching the (real) planner call.
    with patch(
        "vlm_photo_editor.detection.detect_subject", side_effect=ValueError("stop here")
    ) as detect:
        at = AppTest.from_file("vlm_photo_editor/app/main.py")
        at.session_state["uploaded_file"] = SimpleNamespace(name="fake.jpg", size=123)
        at.session_state["_loaded_file_id"] = "fake.jpg:123"
        at.session_state["container"] = container
        at.session_state["ui_phase"] = "has_image"
        at.session_state["edit_mode"] = "frame"
        at.session_state["framing_mode"] = "rule_of_thirds"
        at.session_state["character_focus"] = "coco"
        at.session_state["character_focus_targets"] = ["dog"]
        at.run(timeout=90)
    assert not at.exception
    detect.assert_called()
    assert detect.call_args.args[1:] == ("coco", ["dog"])
