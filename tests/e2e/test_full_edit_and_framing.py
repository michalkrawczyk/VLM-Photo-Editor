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
    save_and_get_path,
    select_dropdown_option,
    select_edit_mode,
    snap,
    upload_image,
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


@pytest.mark.parametrize("framing_mode", ["rule_of_thirds", "face_only", "portrait_headroom"])
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
