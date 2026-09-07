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
- Per-image preview strip before **Start Batch Processing** — thumbnails with prev/next navigation reusing `app/components/preview.py`, so the user can confirm the upload set and (once staged planning / per-image framing lands) review each image's plan before committing the batch.

**Dependencies:** D10 multi-image navigation must be in place first (upload already supports `accept_multiple_files=True`).

---

## vLLM & llama.cpp Local Loader Backends + Loader Auto-Detect / On-Demand Install

Moved out of build-plan P10. MVP needs only one local loader (`transformers` or `ollama`, the existing defaults) for the `critic` / `cost_router` / `input_guard` roles.

**Deferred scope:**
- `loader="vllm"` — `langchain_openai.ChatOpenAI(base_url=...)` against a running vLLM OpenAI-compatible server (`ModelEntry.vllm_base_url`, default `"http://localhost:8000/v1"`). GPU-oriented throughput for large batch runs.
- `loader="llamacpp"` — `langchain_community.chat_models.ChatLlamaCpp` over a local GGUF file (`ModelEntry.gguf_path`). CPU-friendly for the 1.2B text-only models.
- `registry.available_loaders()` — probe installed packages via `importlib.util.find_spec` (plus an HTTP health probe for vLLM) and return which loaders are ready.
- `registry.install_loader_deps(loader)` — `sys.executable -m pip install -r requirements-<loader>.txt` as a subprocess; unknown loader raises `ValueError`.
- Settings UI "Local Model Backends" expander (`app/components/settings.py`) — per-loader status badge + Install / Ping buttons.

**Status:** implementation already exists in the tree (`models/registry.py`, `app/components/settings.py`). This entry records that it is out of MVP acceptance scope — not that it must be removed.

**Trigger for adoption:** a batch workflow that needs vLLM throughput, or a target user whose hardware can't run the `transformers` default.

---

## Photoshop PS-Strict Mode + MCP / UXP Bridge

Moved out of build-plan P9 (which now covers the Critic layer only). Supersedes the "Photoshop backend (P9)" line under "Additional Deferred Items".

**Deferred scope:**
- PS-strict policy enforcement — intersect the compiler's allowed-op set with `{n for n, s in all_specs().items() if s.ps_expressible}` when the policy mode is PS-strict. Today this is prompt prose only (see `plans/issues.md` SC-P3 / PL-P4); needs the policy mode threaded into `Compiler.compile()`.
- No-PS mode messaging when Photoshop is unavailable.
- MCP server wrapping UXP / ExtendScript with capability discovery; feed the PS op vocabulary into the planner prompt.

**Kept in MVP:** the `AcceptMode` / policy enums and the `ps_expressible` flag stay; only enforcement + the bridge are deferred.

**Trigger for adoption:** a user workflow that genuinely requires Photoshop-only edits, or demand for the UXP bridge.

---

## Operation Progress Feedback

Name each operation as it runs instead of a single indeterminate bar.

**Motivation:** During execution the UI shows one static `st.progress(0.0, text="Applying edits…")` (`app/main.py:318,325`); batch shows `text="Planned N/M images…"` (`app/main.py:476-483`). On a multi-op plan the user has no signal which op is running or how many remain. `pipeline/job_queue.py:19-37` only fires `on_progress(1.0)` on completion and already carries an "Extend for incremental updates" comment.

**Proposed design:**
- Extend `run_job` / `Executor.apply` with an `on_step(index, total, op_name)` callback; the executor calls it per op inside the `for op in op_graph.ops` loop (`ops/executor.py:49`).
- UI passes `st.progress((i + 1) / total, text=f"{i + 1}/{total}: {op_name}…")`.
- Batch panel reuses the same callback per image (the existing "individual errors reported per-file" bullet under Batch Processing already assumes per-item iteration — same hook).

**Trigger for adoption:** whenever plans routinely exceed 3–4 ops, or batch runs make the single bar feel unresponsive.

---

## Staged Full Edit (Frame → Correct)

Split `edit_mode == "full"` into a framing stage and a correction stage.

**Motivation:** `templates/full_edit.txt` is a one-line prompt producing a single `HumanPlan` → one `OpGraph` → one `_do_execute()` pass. Crop and tonal ops are planned together against the original framing. Cropping changes the composition and the effective histogram, so exposure / white-balance / contrast planned against the uncropped image can be wrong for the cropped result. A photographer's real workflow is crop first, then grade.

**Design:** when `edit_mode == "full"`, the planner runs twice, sequentially.
- **Stage 1 — Framing.** Planner produces a crop/frame-only `HumanPlan` (crop, frame, rotate only), shown in `plan_view` under a "Stage 1 — Framing" header. On approval it is compiled and executed against the original container, yielding the cropped container.
- **Stage 2 — Corrections.** After stage 1 executes, the cropped container is re-encoded and the planner plans tonal / color / cleanup / genAI ops on it, shown under a "Stage 2 — Corrections" header directly below stage 1 — both plans visible together once stage 2 exists. Approving stage 2 executes it on the cropped container.
- A change request against stage 1 re-plans stage 1 and discards stage 2 (planned against a now-stale crop); a change request against stage 2 re-plans only stage 2.
- `AcceptMode` auto-tiers apply per stage independently (a LOW-only stage 1 auto-executes under `auto_low`, then stage 2 gates on its own tier).
- The Recipe records the union of both stages' ops, in execution order, as a single replayable sequence — no schema change, one `OpGraph` assembled from both stages.

**Reference points:** `templates/full_edit.txt`, `agents/planner.py`, `planner/compiler.py`, `app/components/plan_view.py`, `_do_generate_plan` / `_do_execute` in `app/main.py`.

**Trigger for adoption:** once single-stage full-edit results are frequently corrected for exposure/WB that read fine before the crop.

---

## Clarifying Questions When Intent Is Ambiguous

Let the planner ask a structured multiple-choice question before building a plan.

**Motivation:** an under-specified instruction ("fix this photo", "make it pop") yields a best-guess `HumanPlan` the user then corrects through the free-text change-request loop (`_do_revise_plan` in `app/main.py`, `agents/planner.py:revise`). A structured prompt — the interaction model of the Claude Code AskUserQuestion / VS Code question popup — resolves the ambiguity up front, before any plan is built.

**Design:**
- Add an optional `clarification` branch to planner output: instead of (or before) a `HumanPlan`, the planner may return a `ClarificationRequest` — a question string plus 2–4 labelled options (and an implicit free-text "Other"), mirroring the AskUserQuestion schema (`question`, `header`, `options[].label`, `options[].description`).
- New schema type in `schema/` (root dep, imports nothing from siblings), e.g. `schema/clarify.py::ClarificationRequest` / `ClarificationOption`.
- `agents/planner.py` gains a pre-plan pass (or a structured-output union return) that decides "ask vs. plan"; a confidence/ambiguity signal in the system prompt gates it. Bounded — at most one clarification round per generate, then fall back to a best-guess plan so the flow can't stall.
- UI: render the request in the single-image flow between the intent box and `plan_view` as `st.radio` + an "Other" `st.text_input`; the answer is appended to `intent` (or passed as structured context) and `_do_generate_plan()` re-runs. Batch mode: one clarification for the whole set, asked once before `run_batch`.
- `AcceptMode.full_auto` / `auto_*` skip the question — never block an unattended run.

**Contrast:** this is a *pre-plan* gate; the existing change-request loop is *post-plan*.

**Reference points:** `agents/planner.py`, `agents/edit_flow.py`, `schema/plan.py`, `app/components/plan_view.py`, `_do_generate_plan` / `_do_revise_plan` in `app/main.py`.

**Trigger for adoption:** when change-request rounds are dominated by "you guessed wrong about what I meant" rather than genuine plan refinement.

---

## Additional Deferred Items

- **Output directory picker (B7):** Let users choose a destination folder instead of always saving beside the temp upload path.
- **Photoshop backend (P9):** see "Photoshop PS-Strict Mode + MCP / UXP Bridge" above.
- **Subject-aware framing (D13):** Face/saliency detection to drive FRAME ops rather than the current center-crop stub.
- **AcceptMode AUTO / FULL_AUTO (B6):** Hook `edit_flow.py` LangGraph into the UI so mode switches have effect.
