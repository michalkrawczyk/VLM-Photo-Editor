# Future Improvements

Items deferred from the current build plan — not required for MVP but worth tracking.

---

## Batch Processing

Allow users to apply the same edit plan to multiple images in a single session.

**Motivation:** Photographers often shoot a sequence under identical conditions (same lighting, framing intent, color treatment). Re-running the plan one image at a time is tedious once the plan is approved.

**Proposed design:**
- After the user approves a plan on the first image, expose a "Apply to all" button that runs the Executor against every image in `state["uploaded_files"]`.
- Progress shown via `st.progress` bar; individual errors reported per-file without aborting the batch.
- Each output file gets its own recipe sidecar (`{stem}_edited.edit.json`).
- Batch results shown as a summary table (filename, status, saved path) after all images complete.

**Dependencies:** D10 multi-image navigation must be in place first (upload already supports `accept_multiple_files=True`).

---

## Additional Deferred Items

- **Output directory picker (B7):** Let users choose a destination folder instead of always saving beside the temp upload path.
- **Photoshop backend (P9):** Wire up the PS-strict execution policy with an actual Photoshop connection.
- **Subject-aware framing (D13):** Face/saliency detection to drive FRAME ops rather than the current center-crop stub.
- **AcceptMode AUTO / FULL_AUTO (B6):** Hook `edit_flow.py` LangGraph into the UI so mode switches have effect.
