"""Live-browser e2e for the two batch modes (real Streamlit + real Anthropic API).

Not run by default — ``pytest -m e2e``. Costs API credit; needs ANTHROPIC_API_KEY.

Mode A: checkbox ON, one shared instruction, plan approved once, recompiled and
executed per image. Mode B: checkbox OFF, one instruction box per image, each
planned with its own instruction and reviewed in the queue.

Locators track visible label/button text in app/main.py + components/batch_review.py
— Streamlit does not expose ``key=`` as a DOM id.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._helpers import (
    click_button,
    set_accept_mode,
    snap,
    wait_for_idle,
)

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


def _copies(src: Path, dst_dir: Path, n: int) -> list[Path]:
    out: list[Path] = []
    for i in range(n):
        p = dst_dir / f"batch_{i}{src.suffix}"
        shutil.copyfile(src, p)
        out.append(p)
    return out


def _upload_many(page: Page, paths: list[Path]) -> None:
    page.locator('input[type="file"]').set_input_files([str(p) for p in paths])
    expect(page.get_by_text("Batch Processing —", exact=False)).to_be_visible(timeout=20_000)
    wait_for_idle(page)


def _saved_dir_from_banner(page: Page, expected_count: int) -> Path:
    banner = page.locator('[data-testid="stAlertContentSuccess"]').filter(has_text="Saved")
    expect(banner.first).to_be_visible(timeout=30_000)
    text = banner.first.inner_text()
    m = re.search(rf"Saved {expected_count} files to (.+?)\.?$", text.strip())
    assert m, f"unexpected save banner: {text!r}"
    return Path(m.group(1))


def test_batch_mode_a_apply_same_edit_to_every_image(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    screenshot_dir: Path,
    tmp_path: Path,
) -> None:
    originals = _copies(sample_image_jpg, tmp_path, 3)
    orig_bytes = [p.read_bytes() for p in originals]

    page.goto(streamlit_server)
    _upload_many(page, originals)
    snap(page, screenshot_dir, "batch_mode_a_01_uploaded")

    # Mode A is the default (checkbox ON). Full Auto => the shared plan
    # auto-approves, but the explicit "Apply to all" click is still required.
    set_accept_mode(page, "Full Auto")
    page.get_by_label("What would you like to do with all these images?").fill(
        "brighten slightly and add a touch of contrast"
    )
    page.keyboard.press("Tab")
    wait_for_idle(page)

    click_button(
        page,
        "Preview plan on first image",
        until=page.get_by_text("Proposed Plan", exact=True),
    )
    snap(page, screenshot_dir, "batch_mode_a_02_plan")

    click_button(
        page,
        "Apply to all 3 images",
        until=page.get_by_text("auto-executed", exact=False),
    )
    snap(page, screenshot_dir, "batch_mode_a_03_applied")

    click_button(page, "Save All Accepted (3 images)")
    saved_dir = _saved_dir_from_banner(page, 3)
    recipes_dir = saved_dir.parent.parent / "recipes" / "batch"
    try:
        edited = sorted(saved_dir.glob("batch_*_edited.*"))
        assert len(edited) == 3, f"expected 3 edited files in {saved_dir}, got {edited}"
        sidecars = sorted(recipes_dir.glob("batch_*.edit.json"))
        assert len(sidecars) == 3, f"expected 3 recipe sidecars in {recipes_dir}, got {sidecars}"
        for p, b in zip(originals, orig_bytes):
            assert p.read_bytes() == b, f"original {p} was modified"
    finally:
        for p in list(saved_dir.glob("batch_*")) + list(recipes_dir.glob("batch_*")):
            p.unlink(missing_ok=True)


def test_batch_mode_b_per_image_instructions(
    page: Page,
    streamlit_server: str,
    sample_image_jpg: Path,
    screenshot_dir: Path,
    tmp_path: Path,
) -> None:
    originals = _copies(sample_image_jpg, tmp_path, 2)

    page.goto(streamlit_server)
    _upload_many(page, originals)

    # Untick the checkbox -> Mode B.
    page.get_by_label("Apply the same edit to every image").uncheck()
    wait_for_idle(page)

    page.get_by_label(f"Instruction — {originals[0].name}").fill("make it noticeably warmer")
    page.get_by_label(f"Instruction — {originals[1].name}").fill("convert to black and white")
    page.keyboard.press("Tab")
    wait_for_idle(page)
    snap(page, screenshot_dir, "batch_mode_b_01_instructions")

    click_button(
        page,
        "Start Batch Processing",
        until=page.get_by_text("Review Queue", exact=True).or_(
            page.get_by_text("need review", exact=False)
        ),
    )
    snap(page, screenshot_dir, "batch_mode_b_02_review")

    # Accept every image in the review queue.
    for _ in range(2):
        accept = page.get_by_role("button", name="Accept", exact=True)
        if not accept.count():
            break
        accept.first.click()
        wait_for_idle(page)

    click_button(page, "Save All Accepted (2 images)")
    saved_dir = _saved_dir_from_banner(page, 2)
    recipes_dir = saved_dir.parent.parent / "recipes" / "batch"
    try:
        sidecars = sorted(recipes_dir.glob("batch_*.edit.json"))
        assert len(sidecars) == 2, f"expected 2 recipe sidecars, got {sidecars}"
        from vlm_photo_editor.recipe.store import RecipeStore

        graphs = [RecipeStore.load(s).op_graph.model_dump() for s in sidecars]
        assert graphs[0] != graphs[1], "per-image instructions produced identical op-graphs"
    finally:
        for p in list(saved_dir.glob("batch_*")) + list(recipes_dir.glob("batch_*")):
            p.unlink(missing_ok=True)
