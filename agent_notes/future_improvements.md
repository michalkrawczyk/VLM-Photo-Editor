# Future Improvements

Deferred features and libraries that are intentionally out of scope for the base implementation but worth revisiting once the core is stable.

---

## Precision Codebase Exploration (Explore Agent Replacement / Improvement)

**Problem:** The Explore agent summarizes files rather than returning verbatim content, causing precision loss (exact field names, signatures) during planning. The main context must then re-read the same files directly, doubling reads.

**Option A — Richer AGENTS.md (low-cost, immediate):**
Extend each `vlm_photo_editor/<module>/AGENTS.md` to include actual exported function/class signatures and key field names (not just prose descriptions). An agent reads the AGENTS.md first for precise quick-reference, then reads only the specific file sections it still needs verbatim. No tooling changes required.

**Option B — Auto-generated API manifest:**
Extend `agent_notes/generate_module_map.py` to emit a `module_api.json` alongside the module map, containing exported symbols + signatures per module. An agent queries this JSON for discovery, then reads the target file directly — no summarization step.

**Option C — Annotated "context files" in plan sections:**
Add a "Key files to read for context" subsection to each P-step in `plans/photo_editor_build_plan.md`. Eliminates discovery entirely for planned work; an agent reads the listed files verbatim and proceeds without an Explore pass.

**Trigger for adoption:** Any of these pays off when P-step planning takes more than one round of clarification reads. Option A (richer AGENTS.md) is the cheapest and can be done incrementally as each module stabilizes. Option B is worth doing once all core modules (P0–P6) are complete.

---

## Leonardo.AI API for GenAI Ops

**Why deferred:** Leonardo.AI offers image generation and inpainting via REST API (`/generations/img2img`, `/inpainting`). It would slot in as a `leonardo:` prefix in the provider routing convention established in `background/providers/`. Key: `LEONARDO_API_KEY`. Deferred because API surface, pricing model, and inpainting quality relative to Replicate/OpenAI are not yet evaluated; no official Python SDK exists as of 2026-06.

**Integration point:** New `LeonardoProvider(GenAIProvider)` in `background/providers/leonardo.py`; register prefix in `providers/__init__.py`.

---

## Pre-VLM Face Anonymization

**Problem:** Sending user photos to external VLM/planner APIs (Anthropic, Replicate, etc.) exposes identifiable faces to third-party systems. Users may not expect or consent to this.

**Mechanism:** Before encoding any `ImageContainer` for a VLM API call, run a local face-detection pass (the mediapipe backend in `detection/` already ships for Character Focus; reuse it) and replace each detected face region with a neutral placeholder (solid fill, Gaussian blur, or a synthetic face via a local diffusion model). This anonymized copy is sent to the API; the original pixels are never transmitted. The anonymization is ephemeral — it exists only in the encoded bytes, never written to disk.

**Integration point:** `Planner._encode_image` (currently `vlm_photo_editor/agents/planner.py:119`). Add an optional `anonymize_faces: bool` parameter (default `False`). The session state or `AppSettings` exposes this toggle to the user.

**Scope:** Applies to the planning step only. The executor operates entirely locally on the original pixels.

**Constraints:**
- Anonymization must not alter bounding-box geometry visible to the VLM (blurring is safer than cropping).
- The redaction must be reversible to zero: the unmodified `ImageContainer` must remain accessible in session state after the API call.
- Log that anonymization ran, but never log which regions were masked (face coordinates are PII-adjacent).

**Trigger for adoption:** When the app handles photos of real people in production, or when a user requests a privacy mode. Can reuse the face-detection pre-pass already in `detection/`.

---

## Open-Vocabulary Detection / Visual Grounding for Precise Coordinates

**Problem:** The planner VLM (Claude/GPT) guesses raw pixel `{left, top, right, bottom}` integers for `crop`, and bbox targets for `region_edit`/`background_replace`/`mask`, purely from prose reasoning over the image (`templates/planner.py`) — general-purpose chat VLMs aren't trained for precise pixel grounding, and nothing verifies the numbers before they're compiled into an `Op`. Separately, `ops/backends/pil_backend.py:_frame` ignores composition/subject entirely and does a geometric center-crop — the open question in `plans/issues.md` D13 ("FRAME op planner–executor coordination undefined... provide face bounding boxes from a detection pre-pass"). The shipped Character Focus detectors (`detection/`, closed-set classes) cover the same conceptual slot for fixed classes; a grounding/detection model is the general form — resolving *any* free-text target (e.g. "the trash can," "the person in red") to a verified box.

**Candidates considered:**

| Model | License | Hardware | Open-vocabulary (free-text target)? | Verdict |
|---|---|---|---|---|
| `nvidia/LocateAnything-3B` | NVIDIA — academic/non-profit research only | ~11–35GB VRAM, Ampere+ GPU | Yes (full VLM grounding) | Ruled out — fails both license (non-commercial-only) and hardware (vs. this project's CPU/light-GPU local-model profile: `LFM2.5-1.2B`, `LFM2.5-VL-1.6B`) |
| **YOLO-World** | GPL-v3 (commercial license available on request) | CPU-deployable (ONNX), edge-capable (TFLite/INT8) | Yes — text-prompted, no retraining needed | Best current candidate — matches the actual need (grounding arbitrary planner/user-described targets) and this project's light, CPU-friendly local-model profile far better than a 3B VLM. Confirm commercial license terms before committing if the project ships commercially. |
| RT-DETR / RT-DETRv2 | Apache-2.0 (fully permissive) | GPU-oriented for real-time speed, but ONNX/OpenVINO/CPU deployment documented | No — closed-set detector (COCO/Objects365 classes only) | Cleanest license, lightweight, but only covers generic "person"-class subject boxes (useful for `frame`'s `face_only`/`portrait_headroom` modes), not arbitrary `region_edit`/`background_replace` targets |

**Trigger for adoption:** Revisit once this feature is prioritized. Trial YOLO-World first (best license/capability balance for this project's hardware); fall back to RT-DETR for the narrower "generic subject bbox" case if YOLO-World's license terms don't work out.

**Integration point (whenever a candidate is chosen):** A new registry role (e.g. `"grounding"` or `"detector"`) following the `ModelEntry` pattern already used for `critic`/`cost_router` in `config/registry.py`. Called from `planner/compiler.py` — not exposed to the planner VLM as an op — to resolve semantic targets (e.g. "the face," a `region_edit` prompt) into a verified `BoundingBox` before `Op` construction. This keeps the human-readable plan semantic while making the compiled coordinates deterministic and correct.

---

## Op Catalog / Registry + Custom Op Extension Points

**Status: Extension Point A (the registry itself) implemented — see `vlm_photo_editor/schema/op_catalog.py`.**
`validator.py`, `compiler.py`, and `templates/planner.py` now read from it instead of
five parallel tables. Extension Point B (planner-authored scripts at plan time) remains
out of scope, per the note below — still needs its own threat-model doc.

**Problem:** op definitions are scattered across five places that must be kept in sync by hand: `schema/ops.py` (`OpName` enum), `ops/validator.py` (`_REQUIRED_PARAMS`, `_PARAM_BOUNDS`), `planner/compiler.py` (`_OP_RISK`, `_OP_DEFAULT_BACKEND`), `templates/planner.py` (prose param docs fed to the LLM), and the backend dispatch tables (`ops/backends/pil_backend.py`, `ops/backends/cv_backend.py`). Nothing enforces agreement between them. This is exactly how the `mask` op ended up broken: it was listed in the planner prompt as `mask: {}` with zero semantic documentation, while its actual backend implementation did something (a full-image solid-color fill) that had no relationship to what an LLM would reasonably infer from the name — see the `mask`/`fill_mask` split fix in `planner/compiler.py`/`ops/backends/pil_backend.py` for the concrete incident.

**Proposed shape:** a single `OpSpec` registry, e.g. `vlm_photo_editor/ops/catalog.py` — one entry per `OpName` holding: params + bounds, required fields, risk tier, default/allowed backends, bbox-eligibility class (size-changing / self-managed-inpaint / generic-confinable), and the exact planner-facing doc string. `validator.py`, `compiler.py`, and `templates/planner.py` would read from this registry instead of maintaining five parallel tables that can drift independently.

**Extension point A — developer-registered ops (trusted):** a `register_op(spec, backend_fn)` call a developer adds from a local module to introduce a new op without editing every core file. Still fully vetted code merged into the repo through normal review; the planner only ever proposes ops already present in the catalog. No new execution-time trust boundary — same risk profile as adding an op today, just centralized.

**Extension point B — planner-authored scripts at plan time:** the LLM itself proposes a small novel script as part of a plan, executed as a MEDIUM/HIGH-risk op. Flagged explicitly as a materially bigger, security-sensitive feature — arbitrary AI-authored code execution — with no sandboxing infrastructure anywhere in this codebase today. This needs its own dedicated design/threat-model document (execution sandbox, resource limits, review/approval flow beyond the existing plan-approval UI, secrets isolation) before any implementation. Do not fold into the catalog work above.

**Trigger for adoption:** once another op or two gets added and the scattered-table pattern causes a second sync bug, or before any custom-op work (extension point A or B) begins.

---

## Detector Models: Segmentation Heads & Multi-Output Graphs

**Why deferred:** The pluggable Character Focus registry (`detection/registry.py`) decodes three YOLO output layouts (`yolov8`, `yolov5`, `nms`) via `model.json`. Instance-segmentation exports (extra mask-proto output) and multi-output graphs are not decoded; such models fail with a layout/class-count error.

**Trigger for adoption:** A user model that is worth supporting and cannot be re-exported to one of the three layouts. Would add a `layout` value and, if masks are wanted, a mask path into the freeze region instead of a bbox.

---

## EXIF / XMP / IPTC on 16-bit TIFF and RAW

**Why deferred:** only RAW input yields a 16-bit container, and `loaders._load_raw` sets `metadata={}` (rawpy exposes no EXIF). The 16-bit save path (`savers.py`, tifffile) also cannot write the Exif sub-IFD: tifffile's `extratags` documents "cannot be used to write IFD type tags", so ISO / exposure / lens tags would need a new dependency. ICC is now carried (`iccprofile=`); EXIF is not.

**Trigger for adoption:** an approved dependency that can both read EXIF from RAW (e.g. exifread) and write it into a 16-bit TIFF, or a user need to keep capture metadata on RAW exports. Needs T3 (dep + `stack.md`).
