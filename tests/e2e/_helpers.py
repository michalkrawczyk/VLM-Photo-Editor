"""Shared Playwright step helpers for the live-browser e2e tests.

Locators are tied to visible labels/button text already present in
vlm_photo_editor/app/main.py and components/plan_view.py — Streamlit doesn't
expose st.*(key=...) as a DOM id, so text/role locators are the stable option.

main.py catches backend failures into an st.error banner rather than raising, so
every wait races the expected element against that banner: without the race a
blocked plan or execution just burns the whole timeout with no diagnosis.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import Locator, Page, expect

PLAN_READY_TIMEOUT_MS = 60_000
EXECUTE_TIMEOUT_MS = 60_000


# The settings sidebar permanently renders "No <thing> available. Add an API key…"
# errors for every backend that isn't configured (settings.py:133/176/223/273).
# They are status, not failures, so they must not abort a wait.
_STATIC_SETTINGS_ERROR = re.compile(r"^No .+ available")


def _error_banner(page: Page) -> Locator:
    # Streamlit tags an alert's body by kind: st.error -> stAlertContentError
    # (st.success -> ...Success, st.warning -> ...Warning).
    return page.locator('[data-testid="stAlertContentError"]').filter(
        has_not_text=_STATIC_SETTINGS_ERROR
    )


def _wait_for_or_fail(page: Page, target: Locator, timeout: int, what: str) -> None:
    """Wait for *target*, but fail immediately (with its text) if the app's error
    banner appears first."""
    error = _error_banner(page)
    expect(target.or_(error).first).to_be_visible(timeout=timeout)
    if error.count() and not target.count():
        pytest.fail(f"{what}: app reported an error — {error.first.inner_text().strip()}")


def wait_for_idle(page: Page, timeout: int = 30_000) -> None:
    """Block until Streamlit has finished its rerun.

    Streamlit marks every element container data-stale="true" while a rerun is in
    flight and re-mounts them afterwards; a click landing in that window is
    dropped (the button the click targeted no longer exists when React commits).
    """
    expect(page.locator('[data-stale="true"]')).to_have_count(0, timeout=timeout)


def click_button(
    page: Page,
    name: str,
    *,
    until: Locator | None = None,
    attempts: int = 3,
    until_timeout: int = 15_000,
) -> None:
    """Click a Streamlit button, waiting out any in-flight rerun first.

    With *until*, the click is only believed once that locator (or an app error)
    shows up; otherwise the button is clicked again. Streamlit silently drops a
    click that lands while a rerun is committing, and a dropped click is
    indistinguishable from a slow one until the expected result fails to appear.
    """
    button = page.get_by_role("button", name=name, exact=True)
    for attempt in range(attempts):
        wait_for_idle(page)
        button.click()
        wait_for_idle(page)
        if until is None:
            return
        try:
            expect(until.or_(_error_banner(page)).first).to_be_visible(timeout=until_timeout)
            return
        except AssertionError:
            if attempt == attempts - 1:
                raise


def upload_image(page: Page, path: Path) -> None:
    page.locator('input[type="file"]').set_input_files(str(path))
    expect(page.get_by_text("Loaded:", exact=False)).to_be_visible(timeout=15_000)
    wait_for_idle(page)


def select_edit_mode(page: Page, label: str) -> None:
    """Click one of the Full Edit / Background / Reframe Only mode buttons and
    confirm it took: the active mode button re-renders as Streamlit's primary
    kind, so that flip is the acknowledgement that the click was not dropped."""
    button = page.get_by_role("button", name=label, exact=True)
    active = page.locator('[data-testid="stBaseButton-primary"]').filter(has_text=label)
    for _ in range(3):
        wait_for_idle(page)
        button.click()
        wait_for_idle(page)
        if active.count():
            return
    raise AssertionError(f"mode button {label!r} never became active")


def _open_dropdown(page: Page, label_text: str) -> Locator:
    """Open a Streamlit selectbox and return its option locator.

    Streamlit 1.60 renders selectboxes as a react-aria ComboBox — an
    input[role=combobox] plus an aria-label="Open" button — not the older BaseWeb
    div[data-baseweb="select"]. Options live in a portalled popover, so they are
    located from the page, and waited for: reading straight after the click races
    the popover mounting.
    """
    container = page.locator('div[data-testid="stSelectbox"]').filter(has_text=label_text)
    options = page.get_by_role("option")
    for attempt in range(3):
        wait_for_idle(page)
        container.get_by_role("button", name="Open").click()
        try:
            # A rerun landing on the click drops it, or re-mounts the widget and
            # closes the popover again — reopen rather than fail the test.
            expect(options.first).to_be_visible(timeout=5_000)
            return options
        except AssertionError:
            if attempt == 2:
                raise
    return options


def select_dropdown_option(page: Page, label_text: str, option_text: str) -> None:
    """Drive a Streamlit selectbox to option_text."""
    options = _open_dropdown(page, label_text)
    options.filter(has_text=re.compile(f"^{re.escape(option_text)}$")).click()
    wait_for_idle(page)


def open_dropdown_options(page: Page, label_text: str) -> list[str]:
    """Open a Streamlit selectbox and return its option labels."""
    return _open_dropdown(page, label_text).all_inner_texts()


def wait_for_plan_ready(page: Page, timeout: int = PLAN_READY_TIMEOUT_MS) -> None:
    _wait_for_or_fail(
        page, page.get_by_text("Proposed Plan", exact=True), timeout, "plan generation"
    )


def accept_plan_and_wait_executed(page: Page, timeout: int = EXECUTE_TIMEOUT_MS) -> None:
    wait_for_idle(page)
    page.get_by_role("button", name="Accept Plan", exact=True).click()
    _wait_for_or_fail(page, page.get_by_text("Executed ✓", exact=True), timeout, "execution")


def save_and_get_path(page: Page, timeout: int = 30_000) -> Path:
    wait_for_idle(page)
    page.get_by_role("button", name="Save New File", exact=True).click()
    # Scoped to the success alert: the status caption below also renders "Saved: …",
    # and a bare get_by_text would match both (Playwright strict-mode violation).
    locator = page.locator('[data-testid="stAlertContentSuccess"]').filter(has_text="Saved:")
    _wait_for_or_fail(page, locator, timeout, "save")
    text = locator.first.inner_text()
    return Path(text.split("Saved:", 1)[1].strip())


def cleanup_saved_output(saved_path: Path) -> None:
    """Remove the saved edit and its recipe sidecar (RecipeStore naming: <stem>.edit.json)."""
    sidecar = saved_path.parent / (saved_path.stem.removesuffix("_edited") + ".edit.json")
    saved_path.unlink(missing_ok=True)
    sidecar.unlink(missing_ok=True)


def snap(page: Page, screenshot_dir: Path, name: str) -> None:
    page.screenshot(path=str(screenshot_dir / f"{name}.png"), full_page=True)
