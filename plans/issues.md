# VLM Photo Editor — Bug & Issue Tracker

Audit date: 2026-06-16. All tests pass (122 passed, 2 skipped) but the issues below are either untested paths, design gaps, or principle violations.

---

## BUGS — cause crashes or incorrect behavior

### ~~B1: `_encode_image` crashes on 16-bit (RAW) images~~ ✓ FIXED

Added NORM_MINMAX guard in `_encode_image` (`planner.py:171-182`): non-uint8 pixels are auto-contrast scaled to [0, 255] before `fromarray`. Test `test_encode_image_handles_bit_depth` added (T1 covered).

---

### B2: Revision error causes infinite retry loop
**File:** [vlm_photo_editor/app/main.py:65-84](vlm_photo_editor/app/main.py#L65)

`_do_revise_plan` catches exceptions internally and sets `state["error"]` but does **not** clear `state["change_request"]`. Back in `main.py:279-283`:

```python
change = state.get("change_request") or ""
if change:
    _do_revise_plan(change)
    st.rerun()
```

After a failed revision, `change_request` is still set, `st.rerun()` fires, the revision is attempted again, fails again — infinite loop until the browser is closed.

Fix: add `state.set("change_request", "")` in the `except` block of `_do_revise_plan`.

---

### B4: Canvas bbox coordinates not mapped to image space
**File:** [vlm_photo_editor/app/components/canvas.py:32-55](vlm_photo_editor/app/components/canvas.py#L32)

The canvas is fixed at 600×300 px. Bbox coordinates are in canvas pixels. They are stored directly into `state["bbox"]` and injected into ops verbatim:

```python
bbox = BoundingBox(x=bbox_raw["x"], y=bbox_raw["y"], ...)
```

If the image is 4000×3000, a canvas box at `(100, 50, 200, 100)` covers a tiny corner, not the intended region. Without scaling by `(image_w / 600, image_h / 300)` the region edit operates on the wrong pixels.

Additionally, the canvas doesn't show the actual image so the user is drawing blind. Both problems need to be addressed together (load image into canvas background, then scale coords on read-back).

---

### B5: Uploaded image temp file never deleted
**File:** [vlm_photo_editor/app/main.py:37-40](vlm_photo_editor/app/main.py#L37)

```python
with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
    tmp.write(file.getvalue())
```

`delete=False` and no cleanup path. Every upload leaks a temp file. Large RAWs (30–100 MB each) accumulate in `/tmp` until the OS sweeps them. Fix: track `tmp_path` in session state and delete on new upload or session end, or use `delete=True` + immediately call `load(tmp_path)` before the context manager exits.

---

### B6: `AcceptMode` radio has no functional effect in the UI
**File:** [vlm_photo_editor/app/main.py:194-200](vlm_photo_editor/app/main.py#L194) and [vlm_photo_editor/agents/edit_flow.py](vlm_photo_editor/agents/edit_flow.py)

`accept_mode` is stored in state but `main.py` always goes through the manual path: it waits for `plan_approved = True` regardless of mode. The `AcceptMode.AUTO` / `AcceptMode.FULL_AUTO` auto-approval logic lives in `edit_flow.py` (the LangGraph agent), but `main.py` never uses that graph — it calls `Planner`, `Compiler`, `Executor` directly. Switching the radio to "auto" or "full_auto" does nothing different from "manual".

---

### B7: Saved file and recipe written to `/tmp`
**File:** [vlm_photo_editor/app/main.py:128-136](vlm_photo_editor/app/main.py#L128)

```python
source = edited.source_path   # == temp file path e.g. /tmp/tmpXXXXXX.jpg
dest = source.parent / f"{source.stem}_edited{source.suffix}"
# → /tmp/tmpXXXXXX_edited.jpg
RecipeStore.save(recipe, directory=source.parent)
# → /tmp/tmpXXXXXX.edit.json
```

Output is siloed in the system temp directory, not beside the original upload. The `/tmp` path shown in the success banner confuses users and files may be deleted by OS cleanup.

Fix: determine an actual output directory (e.g., prompt user or use `~/Pictures/vlm_edits/`).

---

### B8: `Recipe.created_at` always empty
**File:** [vlm_photo_editor/app/main.py:135](vlm_photo_editor/app/main.py#L135) and [vlm_photo_editor/schema/recipe.py:22](vlm_photo_editor/schema/recipe.py#L22)

`Recipe(source_path=..., op_graph=...)` uses the default `created_at=""`. The field is never populated. Sidecar files have `"created_at": ""`, making them unsortable by date and harder to inspect.

Fix: default to `datetime.utcnow().isoformat()` in the schema, or populate at call site.

---

## DESIGN ISSUES — incomplete implementations or principle violations

### D1: `_execute` node in `edit_flow.py` is a stub
**File:** [vlm_photo_editor/agents/edit_flow.py:58-60](vlm_photo_editor/agents/edit_flow.py#L58)

```python
def _execute(state: EditState) -> dict:
    # Wired in P7.
    return {}
```

The LangGraph agent graph's execute node does nothing. Even if the graph were hooked up to the UI (see B6), edits would never apply. P7 marked the DoD "User can upload → see plan → edit/accept → preview before/after → save" as complete, but the graph itself isn't wired.

---

### D2: `requires_manual_approval` is dead code
**File:** [vlm_photo_editor/config/policy.py:18-21](vlm_photo_editor/config/policy.py#L18)

`requires_manual_approval(tier, mode)` is defined but never called anywhere in the codebase. The actual approval gating in `edit_flow.py` uses `AcceptMode` directly via `_route_after_compile`. Remove or connect.

---

### D4: `composite` subject-pixel invariant uses `assert` (disabled with `-O`)
**File:** [vlm_photo_editor/background/composite.py:130-134](vlm_photo_editor/background/composite.py#L130)

The DoD invariant "subject pixels are unchanged" is enforced with:

```python
assert np.all(result.pixels[safe_outside] == source.pixels[safe_outside]), ...
```

`assert` is compiled away under `python -O`. This is the most critical safety check in the pipeline and must use an explicit `if not …: raise` instead.

---

### D5: Instruct-model branch in generator is identical to inpaint branch
**File:** [vlm_photo_editor/background/generator.py:110-114](vlm_photo_editor/background/generator.py#L110)

```python
if instruct:
    inp["image"] = io.BytesIO(image_bytes)
else:
    inp["image"] = io.BytesIO(image_bytes)
    inp["mask"] = io.BytesIO(mask_bytes)
```

Both branches set `inp["image"]` identically. The only difference is the mask. Instruction-based edit models typically require a text-only or image+instruction payload, not the same key. This is likely a copy-paste error; the instruct branch should be verified against the actual model API.

---

### D6: `edit_graph` module-level singleton creates a LangGraph on import
**File:** [vlm_photo_editor/agents/edit_flow.py:107](vlm_photo_editor/agents/edit_flow.py#L107)

```python
edit_graph = build_edit_graph()
```

`InMemorySaver` is instantiated at module import time. If this module is imported in a multi-worker Streamlit deployment, each worker gets its own in-memory checkpointer and sessions can't be shared or persisted. The singleton should be removed; callers should construct the graph explicitly.

---

### D7: `seam_metric` threshold in `quality.py` is 10× the `AppSettings` threshold
**File:** [vlm_photo_editor/background/quality.py:47](vlm_photo_editor/background/quality.py#L47) and [vlm_photo_editor/config/settings.py:9](vlm_photo_editor/config/settings.py#L9)

`AppSettings.seam_quality_threshold = 0.15` (plausible for a 0–1 normalized gradient metric). But `run_background_pipeline` passes `threshold=10.0` (hardcoded), and `select_best` uses `threshold: float = 10.0` as its default. The `AppSettings` value is never read by the pipeline. The threshold controlling how often results are flagged for manual review is effectively unconfigured.

---

## MISSING TESTS

### ~~T1: No test for `_encode_image` on 16-bit container (uncovers B1)~~ ✓ FIXED

### T2: No test for revision error path in UI (uncovers B2)

### T3: No test that `AcceptMode.AUTO` skips human approval in the UI flow (uncovers B6)

### T4: No regression test for crop out-of-bounds validation

### T5: `test_raw_16bit` always skipped — no RAW fixture in repo
**File:** [tests/unit/test_imageio.py:83-88](tests/unit/test_imageio.py#L83)

The only test verifying 16-bit RAW handling is permanently skipped because the fixture file doesn't exist. This means the entire RAW codepath is untested in CI.

---

## UI / UX ISSUES

### U0: No save button for result image
**File:** [vlm_photo_editor/app/main.py](vlm_photo_editor/app/main.py)

After execution completes there is no UI button to save the result image. Users have no way to export the edited image from the app. Related to B7 (output goes to `/tmp`).

Fix: add a "Save Result" button in the post-execution UI. On click, write the result to a user-visible location (e.g. `~/Pictures/vlm_edits/`). Display a success message that includes the full saved path and filename, e.g. `Saved: /home/user/Pictures/vlm_edits/photo_edited.jpg`. Debug/log output should also emit the path and filename so it is visible in the Streamlit debug expander.

---

### U1: Layout and edit mode placement
**Files:** [vlm_photo_editor/app/main.py](vlm_photo_editor/app/main.py), [vlm_photo_editor/app/components/preview.py](vlm_photo_editor/app/components/preview.py)

"What would you like to do with this image?" prompt should appear under the image preview, not in a separate section. Edit mode selector should be colocated with "Generate Plan" — they belong together since the mode governs how the plan is generated.

---

### U2: Reframe Only / Background / Full Edit as prompt prefills
**File:** [vlm_photo_editor/app/main.py](vlm_photo_editor/app/main.py)

"Reframe Only", "Background", and "Full Edit" should not be a separate mode selector — they should be prefill shortcuts that populate "What would you like to do with this image?" with a sensible starting prompt for the planner. User can then edit the text before generating the plan.

---

### U3: Auto-generate plan for Reframe Only when mode is not Custom
**File:** [vlm_photo_editor/app/main.py](vlm_photo_editor/app/main.py)

When the user selects "Reframe Only" and the framing mode is anything other than "Custom", the intent is fully specified — no free-text input is needed. In this case, clicking the framing mode should trigger `generate_plan` automatically without requiring a separate button press.

---

### U4: Framing mode needs a "Custom" option
**File:** [vlm_photo_editor/app/main.py](vlm_photo_editor/app/main.py)

Framing mode selector lacks a "Custom" option. When "Custom" is selected, the "What would you like to do with this image?" field becomes required and the user must describe the desired framing before the plan can be generated. All other framing modes are fully specified and should auto-generate (see U3).

---

## DESIGN ISSUES (continued)

### D13: FRAME op planner–executor coordination undefined

The planner proposes `frame` ops with a `mode` string (e.g. `rule_of_thirds`). The PIL backend (`pil_backend._frame`) currently applies only a geometric center crop to a mode-appropriate aspect ratio — no subject detection. This stop-gap prevents crashes but does not satisfy the P5 framing spec.

Design work needed:
- Define how the planner conveys composition intent to a subject-aware backend (e.g. providing face bounding boxes from a detection pre-pass so the crop centers on the subject).
- Decide whether the planner receives saliency/face data as input context before generating frame ops, or whether the executor handles it transparently behind the `FRAME` op interface.
- Route `FRAME` through the P5 framing module once that module is complete, replacing the PIL backend center-crop stub.

---

### D14: Composition mode sends only target aspect ratio — no focus instruction

**File:** framing module / wherever `FRAME` op parameters are constructed for the planner.

Each composition mode (Face Only, Rule of Thirds, Head & Shoulders, etc.) currently passes only the target frame ratio to the planner and executor. It provides no instruction about *what region to prioritize*, so the executor falls back to a geometric center crop that ignores subject position.

Examples of the missing signal:
- **Face Only** — crop tightly around the face bounding box; do not include the torso.
- **Head & Shoulders** — include head + upper chest; exclude legs.
- **Rule of Thirds** — place the primary subject's eye-line on the upper third; do not simply center.
- **Full Body** — ensure feet and top of head are both within frame.

Fix: augment the `FRAME` op payload (or a parallel `FramingIntent` schema) with a short natural-language focus instruction per mode, generated at mode-selection time. The planner can include this in its reasoning; the executor uses it to bias the crop anchor toward the correct subject region (face bbox, eye-line, centroid, etc.) rather than the image center.

This is a prerequisite for D13's subject-aware backend design: the executor needs to know *which* subject region to protect before it can request the right detection pre-pass.
