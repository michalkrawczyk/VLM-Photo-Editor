# Future Improvements

Items deferred from the current build plan — not required for MVP but worth tracking.

---

## Photoshop PS-Strict Mode + MCP / UXP Bridge

Moved out of build-plan P9 (which now covers the Critic layer only).

**Deferred scope:**
- PS-strict policy enforcement — intersect the compiler's allowed-op set with `{n for n, s in all_specs().items() if s.ps_expressible}` when the policy mode is PS-strict. Today the compiler only gates on Photoshop reachability (`settings.ps_mode == "strict"` probe, `planner/compiler.py`) and the op set is prompt prose only (see `plans/issues.md` SC-P3 / PL-P4); needs the policy mode threaded into `Compiler.compile()`.
- Compiler enforcement of `ps_mode == "none"` (the Settings "Photoshop Mode" expander and the strict-mode unavailable warning already exist).
- MCP server wrapping UXP / ExtendScript with capability discovery; feed the PS op vocabulary into the planner prompt.

**Kept in MVP:** the `AcceptMode` / policy enums and the `ps_expressible` flag stay; only enforcement + the bridge are deferred.

**Trigger for adoption:** a user workflow that genuinely requires Photoshop-only edits, or demand for the UXP bridge.

---

## Operation Progress Feedback

Name each operation as it runs instead of a single indeterminate bar.

**Motivation:** During execution the UI shows one static `st.progress(0.0, text="Applying edits…")` (`app/main.py:360-367`); batch shows per-image bars (`app/main.py:668-691`, `:739-762`). On a multi-op plan the user has no signal which op is running or how many remain. `pipeline/job_queue.py:19-37` only fires `on_progress(1.0)` on completion and already carries an "Extend for incremental updates" comment.

**Proposed design:**
- Extend `run_job` / `Executor.apply` with an `on_step(index, total, op_name)` callback; the executor calls it per op inside the `for op in op_graph.ops` loop (`ops/executor.py:49`).
- UI passes `st.progress((i + 1) / total, text=f"{i + 1}/{total}: {op_name}…")`.
- Batch panel reuses the same callback per image (P11's per-image iteration + "needs attention" per-file error list already assume the same hook).

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

## Pre-VLM Face Anonymization

**Problem:** Sending user photos to external VLM/planner APIs (Anthropic, Replicate, etc.) exposes identifiable faces to third-party systems. Users may not expect or consent to this.

**Mechanism:** Before encoding any `ImageContainer` for a VLM API call, run a local face-detection pass (the mediapipe backend in `detection/` already ships for Character Focus; reuse it) and replace each detected face region with a neutral placeholder (solid fill, Gaussian blur, or a synthetic face via a local diffusion model). This anonymized copy is sent to the API; the original pixels are never transmitted. The anonymization is ephemeral — it exists only in the encoded bytes, never written to disk.

**Integration point:** `Planner._encode_image` (`vlm_photo_editor/agents/planner.py:296`). Add an optional `anonymize_faces: bool` parameter (default `False`). The session state or `AppSettings` exposes this toggle to the user.

**Scope:** Applies to the planning step only. The executor operates entirely locally on the original pixels.

**Constraints:**
- Anonymization must not alter bounding-box geometry visible to the VLM (blurring is safer than cropping).
- The redaction must be reversible to zero: the unmodified `ImageContainer` must remain accessible in session state after the API call.
- Log that anonymization ran, but never log which regions were masked (face coordinates are PII-adjacent).

**Trigger for adoption:** When the app handles photos of real people in production, or when a user requests a privacy mode.

---

## Open-Vocabulary Detection / Visual Grounding for Precise Coordinates

**Problem:** The planner VLM (Claude/GPT) guesses raw pixel `{left, top, right, bottom}` integers for `crop`, and bbox targets for `region_edit`/`background_replace`/`mask`, purely from prose reasoning over the image (`templates/planner.py`) — general-purpose chat VLMs aren't trained for precise pixel grounding, and nothing verifies the numbers before they're compiled into an `Op`. FRAME ops already centre on the Character Focus box (`focus_*` params, `pil_backend.frame_crop_box`), but only for fixed detector classes and only when the toggle is on. A grounding/detection model is the general form — resolving *any* free-text target (e.g. "the trash can," "the person in red") to a verified box.

**Candidates considered:**

| Model | License | Hardware | Open-vocabulary (free-text target)? | Verdict |
|---|---|---|---|---|
| `nvidia/LocateAnything-3B` | NVIDIA — academic/non-profit research only | ~11–35GB VRAM, Ampere+ GPU | Yes (full VLM grounding) | Ruled out — fails both license (non-commercial-only) and hardware (vs. this project's CPU/light-GPU local-model profile: `LFM2.5-1.2B`, `LFM2.5-VL-1.6B`) |
| **YOLO-World** | GPL-v3 (commercial license available on request) | CPU-deployable (ONNX), edge-capable (TFLite/INT8) | Yes — text-prompted, no retraining needed | Best current candidate — matches the need and this project's light, CPU-friendly local-model profile far better than a 3B VLM. Confirm commercial license terms before committing if the project ships commercially. |
| RT-DETR / RT-DETRv2 | Apache-2.0 (fully permissive) | GPU-oriented for real-time speed, but ONNX/OpenVINO/CPU deployment documented | No — closed-set detector (COCO/Objects365 classes only) | Cleanest license, lightweight, but only covers generic "person"-class subject boxes (useful for `frame`'s `face_only`/`portrait_headroom` modes), not arbitrary `region_edit`/`background_replace` targets |

**Trigger for adoption:** Revisit once this feature is prioritized. Trial YOLO-World first; fall back to RT-DETR for the narrower "generic subject bbox" case if YOLO-World's license terms don't work out.

**Integration point (whenever a candidate is chosen):** A new registry role (e.g. `"grounding"` or `"detector"`) following the `ModelEntry` pattern already used for `critic`/`cost_router` in `config/registry.py`. Called from `planner/compiler.py` — not exposed to the planner VLM as an op — to resolve semantic targets into a verified `BoundingBox` before `Op` construction. This keeps the human-readable plan semantic while making the compiled coordinates deterministic and correct.

---

## Planner-Authored Scripts (Op Catalog Extension Point B)

The op registry and developer-registered ops (Extension Point A) shipped — see `vlm_photo_editor/schema/op_catalog.py`. Still out of scope: the LLM proposing a small novel script as part of a plan, executed as a MEDIUM/HIGH-risk op. This is arbitrary AI-authored code execution with no sandboxing infrastructure in this codebase. Needs its own design/threat-model document first (execution sandbox, resource limits, review/approval flow beyond the existing plan-approval UI, secrets isolation). Do not fold into catalog work.

**Trigger for adoption:** a concrete workflow that no catalog op can express.

---

## Leonardo.AI API for GenAI Ops

**Why deferred:** Leonardo.AI offers image generation and inpainting via REST API (`/generations/img2img`, `/inpainting`). It would slot in as a `leonardo:` prefix in the provider routing convention established in `background/providers/`. Key: `LEONARDO_API_KEY`. Deferred because API surface, pricing, and inpainting quality relative to Replicate/OpenAI are not evaluated; no official Python SDK exists as of 2026-06.

**Integration point:** New `LeonardoProvider(GenAIProvider)` in `background/providers/leonardo.py`; register prefix in `providers/__init__.py`.

---

## Detector Models: Segmentation Heads & Multi-Output Graphs

**Why deferred:** The pluggable Character Focus registry (`detection/registry.py`) decodes three YOLO output layouts (`yolov8`, `yolov5`, `nms`) via `model.json`. Instance-segmentation exports (extra mask-proto output) and multi-output graphs are not decoded; such models fail with a layout/class-count error.

**Trigger for adoption:** A user model that is worth supporting and cannot be re-exported to one of the three layouts. Would add a `layout` value and, if masks are wanted, a mask path into the freeze region instead of a bbox.

---

## EXIF / XMP / IPTC on 16-bit TIFF and RAW

**Why deferred:** only RAW input yields a 16-bit container, and `loaders._load_raw` sets `metadata={}` (rawpy exposes no EXIF). The 16-bit save path (`savers.py`, tifffile) also cannot write the Exif sub-IFD: tifffile's `extratags` documents "cannot be used to write IFD type tags", so ISO / exposure / lens tags would need a new dependency. ICC is carried (`iccprofile=`); EXIF is not.

**Trigger for adoption:** an approved dependency that can both read EXIF from RAW (e.g. exifread) and write it into a 16-bit TIFF, or a user need to keep capture metadata on RAW exports. Needs T3 (dep + `stack.md`).

---

## Additional Deferred Items

- **Output directory picker (B7):** Saves now go to `settings.output_dir` (default `~/Pictures/vlm_edits`, or `$VLM_OUTPUT_DIR`). Still missing: a per-save destination picker in the UI.
- **Subject-aware framing (D13):** The center-crop stub is gone; FRAME ops centre on the detected subject when Character Focus is on. Still missing: automatic face/saliency detection without the Character Focus toggle.
