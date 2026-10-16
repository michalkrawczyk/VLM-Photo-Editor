"""Live-browser smoke tests: real Streamlit app, real Anthropic API, real MediaPipe
detection. Not run by default — see agent_notes/commands.md ('pytest -m e2e').

Covers the three flows most exposed to planner/compiler/executor integration risk:
Full Edit, Reframe Only (three Composition modes), and Character Focus.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.e2e._helpers import (
    accept_plan_and_wait_executed,
    cleanup_saved_output,
    click_button,
    open_dropdown_options,
    request_plan_change,
    save_and_get_path,
    select_dropdown_option,
    select_edit_mode,
    set_accept_mode,
    snap,
    upload_image,
    wait_for_executed,
    wait_for_idle,
    wait_for_plan_ready,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def test_full_edit_flow(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    screenshot_dir: Path,
    mediapipe_usable: bool,
) -> None:
    page.goto(streamlit_server)
    upload_image(page, sample_image_jpg)
    snap(page, screenshot_dir, "full_edit_01_uploaded")

    select_edit_mode(page, "Full Edit")
    if mediapipe_usable:
        # Character Focus on: a 'mask' step compiles to invert=True/bbox=None without
        # a detected subject, and _do_execute then blocks on a hand-drawn Region
        # Selection. Skipped where mediapipe would abort the server (see conftest).
        select_dropdown_option(page, "Character Focus:", "mediapipe")
    click_button(page, "Generate Plan", until=page.get_by_text("Proposed Plan", exact=True))
    wait_for_plan_ready(page)
    snap(page, screenshot_dir, "full_edit_02_plan")

    accept_plan_and_wait_executed(page)
    snap(page, screenshot_dir, "full_edit_03_executed")

    saved = save_and_get_path(page)
    snap(page, screenshot_dir, "full_edit_04_saved")
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
    finally:
        cleanup_saved_output(saved)


def test_manual_mode_full_combo_saves_new_file_and_leaves_original_byte_identical(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    screenshot_dir: Path,
) -> None:
    """P8.5 gate, manual mode: upload -> plan -> chat change request -> revised plan
    -> accept -> execute -> save a new file, original untouched. Needs a real
    ANTHROPIC_API_KEY (as every e2e test does). If the live planner emits a region
    op that needs a hand-drawn bbox, the app surfaces an error banner and this test
    fails — expected for an opt-in ``-m e2e`` run; the always-green guarantee for the
    background path is tests/integration/test_p8_5_mvp_gate.py.
    """
    orig = sample_image_jpg.read_bytes()

    page.goto(streamlit_server)
    upload_image(page, sample_image_jpg)
    select_edit_mode(page, "Full Edit")
    click_button(page, "Generate Plan", until=page.get_by_text("Proposed Plan", exact=True))
    wait_for_plan_ready(page)
    snap(page, screenshot_dir, "p8_5_manual_01_plan")

    request_plan_change(
        page,
        "swap the background for a soft neutral studio backdrop, straighten the "
        "horizon, and brighten slightly",
    )
    snap(page, screenshot_dir, "p8_5_manual_02_revised")

    accept_plan_and_wait_executed(page)
    snap(page, screenshot_dir, "p8_5_manual_03_executed")

    saved = save_and_get_path(page)
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
        sidecar = saved.parent / (saved.stem.removesuffix("_edited") + ".edit.json")
        assert sidecar.exists(), f"recipe sidecar {sidecar} not written"
        assert sample_image_jpg.read_bytes() == orig, "original file was modified"
    finally:
        cleanup_saved_output(saved)


def test_full_auto_mode_executes_without_an_accept_click(
    page: Page,
    streamlit_server: str,
    sample_image_png: Path,
    screenshot_dir: Path,
) -> None:
    """P8.5 gate, accept-mode behaviour: with Full Auto selected the plan runs with
    no pre-execution gate — "Executed ✓" appears without clicking "Accept Plan"."""
    page.goto(streamlit_server)
    upload_image(page, sample_image_png)
    set_accept_mode(page, "Full Auto")
    # Reframe Only auto-generates a plan of LOW-risk crop ops (no bbox prompt), so
    # Full Auto executes it straight through.
    select_edit_mode(page, "Reframe Only")

    wait_for_executed(page)
    snap(page, screenshot_dir, "p8_5_full_auto_01_executed")

    saved = save_and_get_path(page)
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
    finally:
        cleanup_saved_output(saved)


# face_only is intentionally excluded: it is offered in the Composition dropdown only
# when the active Character Focus backend exposes a "face" class (none do here), so
# select_dropdown_option would not find it. portrait_headroom shares its 3:4 geometry.
@pytest.mark.parametrize("framing_mode", ["rule_of_thirds", "negative_space", "portrait_headroom"])
def test_reframe_only_flow(
    page: Page,
    streamlit_server: str,
    sample_image_png: Path,
    screenshot_dir: Path,
    framing_mode: str,
) -> None:
    page.goto(streamlit_server)
    upload_image(page, sample_image_png)
    snap(page, screenshot_dir, f"reframe_{framing_mode}_01_uploaded")

    # Composition first: switching to Reframe Only auto-generates a plan (U3), so
    # picking the mode afterwards would race a plan already in flight and pay for
    # two planner calls.
    if framing_mode != "rule_of_thirds":
        select_dropdown_option(page, "Composition:", framing_mode)
    select_edit_mode(page, "Reframe Only")

    wait_for_plan_ready(page)
    snap(page, screenshot_dir, f"reframe_{framing_mode}_02_plan")

    accept_plan_and_wait_executed(page)
    snap(page, screenshot_dir, f"reframe_{framing_mode}_03_executed")

    saved = save_and_get_path(page)
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
    finally:
        cleanup_saved_output(saved)


_GPT6_PRESET_SLUG = {
    "gpt-6.1-sol": "gpt6_1-sol",
    "gpt-6.1-sol (no reasoning)": "gpt6_1-sol-noreason",
    "gpt-6-luna": "gpt6-luna",
    "gpt-6-astra": "gpt6-astra",
}


@pytest.mark.parametrize("planner_preset", list(_GPT6_PRESET_SLUG))
def test_character_focus_yolo_onnx_gpt6(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    yolo_onnx_model_path: Path | None,
    yolo_onnx_usable: bool,
    screenshot_dir: Path,
    planner_preset: str,
) -> None:
    """Character Focus via the ``yolo_onnx`` backend, planned by a gpt-6 preset.

    Reframe Only flow: a ``None`` detection degrades to a centre crop rather than
    blocking on a hand-drawn Region Selection (unlike Full Edit's mask step). Skips
    unless ``onnxruntime`` is importable and a YOLO ``.onnx`` is configured
    (``E2E_YOLO_ONNX_MODEL_PATH`` or ``infer_models/yolo/yolo26s.onnx``). Needs a live
    ``OPENAI_API_KEY`` — asserted via the Planner dropdown before selecting.
    """
    if not yolo_onnx_usable:
        pytest.skip(
            "yolo_onnx backend unusable here: onnxruntime missing, or no YOLO .onnx "
            "(set E2E_YOLO_ONNX_MODEL_PATH or drop one at infer_models/yolo/yolo26s.onnx)"
        )

    slug = _GPT6_PRESET_SLUG[planner_preset]
    page.goto(streamlit_server)
    upload_image(page, sample_image_jpg)
    snap(page, screenshot_dir, f"cf_yolo_{slug}_01_uploaded")

    planner_opts = open_dropdown_options(page, "Planner:")
    assert planner_preset in planner_opts, (
        f"{planner_preset!r} not offered in the Planner dropdown — is OPENAI_API_KEY "
        f"live? got {planner_opts}"
    )
    page.get_by_role("option", name=planner_preset, exact=True).click()
    wait_for_idle(page)

    cf_opts = open_dropdown_options(page, "Character Focus:")
    assert "yolo_onnx" in cf_opts, f"expected 'yolo_onnx' in Character Focus options, got {cf_opts}"
    page.get_by_role("option", name="yolo_onnx", exact=True).click()
    wait_for_idle(page)

    # Planner + backend set first: switching to Reframe Only auto-generates the plan
    # (U3), so picking either afterwards would race a plan already in flight.
    select_edit_mode(page, "Reframe Only")
    snap(page, screenshot_dir, f"cf_yolo_{slug}_02_before_plan")

    wait_for_plan_ready(page)
    snap(page, screenshot_dir, f"cf_yolo_{slug}_03_plan")

    accept_plan_and_wait_executed(page)
    snap(page, screenshot_dir, f"cf_yolo_{slug}_04_executed")

    saved = save_and_get_path(page)
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
    finally:
        cleanup_saved_output(saved)


def test_character_focus_flow(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    mediapipe_model_path: Path,
    screenshot_dir: Path,
    mediapipe_usable: bool,
) -> None:
    if not mediapipe_usable:
        pytest.skip(
            "mediapipe's TFLite binary aborts on this CPU (needs AVX); selecting it "
            "would kill the Streamlit server the whole session shares"
        )

    page.goto(streamlit_server)
    upload_image(page, sample_image_jpg)
    snap(page, screenshot_dir, "character_focus_01_uploaded")

    option_texts = open_dropdown_options(page, "Character Focus:")
    assert "off" in option_texts, f"expected 'off' in Character Focus options, got {option_texts}"
    assert "mediapipe" in option_texts, (
        f"expected 'mediapipe' in Character Focus options (mediapipe is importable in "
        f".venv), got {option_texts}"
    )
    page.get_by_role("option", name="mediapipe", exact=True).click()

    select_edit_mode(page, "Reframe Only")
    snap(page, screenshot_dir, "character_focus_02_before_plan")

    # Prior to the MEDIAPIPE_MODEL_PATH env fallback, this selection deterministically
    # raised ValueError (no model path configured) and the plan never rendered.
    wait_for_plan_ready(page)
    snap(page, screenshot_dir, "character_focus_03_plan")

    accept_plan_and_wait_executed(page)
    snap(page, screenshot_dir, "character_focus_04_executed")

    saved = save_and_get_path(page)
    try:
        assert saved.exists(), f"Save reported {saved} but file does not exist"
    finally:
        cleanup_saved_output(saved)
