# Future Improvements

Deferred features and libraries that are intentionally out of scope for the base implementation but worth revisiting once the core is stable.

---

## Local Face Detection & Subject Segmentation

**Library:** `mediapipe>=0.10`

**Why deferred:** The base implementation delegates face detection and subject masking to the VLM via vision input. mediapipe is a purely local, zero-API-cost alternative that would reduce latency (sub-10 ms vs. ~500 ms API round-trip) and eliminate per-image cost for these geometric ops.

**Trigger for adoption:** Once the VLM-based path is proven correct and the op interface is stable, mediapipe can be dropped in as the geometry backend while the VLM retains high-level planning responsibility.

**Install:** `pip install mediapipe>=0.10`

**Alternative considered:** `face-recognition` (dlib) — heavier build dependency (requires CMake and dlib compile); mediapipe is pip-installable and covers both detection and segmentation in one package.

---

## Structured / JSON Logging

**Library:** `structlog>=24.0`

**Why deferred:** The only current logging requirement is API-key redaction, which stdlib's root-level `logging.Filter` covers without extra dependencies (see `stack.md`). structlog's explicit processor pipeline becomes worth the dependency if the project adds a remote log sink (e.g. Loki, Datadog), needs machine-parseable JSON output, or wants structured key-value event dicts across the codebase.

**Trigger for adoption:** When a log aggregation service is wired up, or when structured event fields (e.g. `image_id`, `op_name`, `duration_ms`) are needed alongside the message.

**Install:** `pip install structlog>=24.0`

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

**Mechanism:** Before encoding any `ImageContainer` for a VLM API call, run a local face-detection pass (mediapipe or similar — see Local Face Detection above) and replace each detected face region with a neutral placeholder (solid fill, Gaussian blur, or a synthetic face via a local diffusion model). This anonymized copy is sent to the API; the original pixels are never transmitted. The anonymization is ephemeral — it exists only in the encoded bytes, never written to disk.

**Integration point:** `Planner._encode_image` (currently `vlm_photo_editor/agents/planner.py:119`). Add an optional `anonymize_faces: bool` parameter (default `False` until mediapipe is added as a dependency). The session state or `AppSettings` exposes this toggle to the user.

**Scope:** Applies to the planning step only. The executor operates entirely locally on the original pixels.

**Constraints:**
- Anonymization must not alter bounding-box geometry visible to the VLM (blurring is safer than cropping).
- The redaction must be reversible to zero: the unmodified `ImageContainer` must remain accessible in session state after the API call.
- Log that anonymization ran, but never log which regions were masked (face coordinates are PII-adjacent).

**Trigger for adoption:** When the app handles photos of real people in production, or when a user requests a privacy mode. Should be implemented alongside the mediapipe integration since both share the same face-detection pre-pass.

---

## Open-Vocabulary Detection / Visual Grounding for Precise Coordinates

**Problem:** The planner VLM (Claude/GPT) guesses raw pixel `{left, top, right, bottom}` integers for `crop`, and bbox targets for `region_edit`/`background_replace`/`mask`, purely from prose reasoning over the image (`templates/planner.py`) — general-purpose chat VLMs aren't trained for precise pixel grounding, and nothing verifies the numbers before they're compiled into an `Op`. Separately, `ops/backends/pil_backend.py:_frame` ignores composition/subject entirely and does a geometric center-crop — the open question in `plans/issues.md` D13 ("FRAME op planner–executor coordination undefined... provide face bounding boxes from a detection pre-pass"). The Local Face Detection & Subject Segmentation entry above (mediapipe) covers the same conceptual slot but only for faces; a grounding/detection model is the general form — resolving *any* free-text target (e.g. "the trash can," "the person in red") to a verified box.

**Candidates considered:**

| Model | License | Hardware | Open-vocabulary (free-text target)? | Verdict |
|---|---|---|---|---|
| `nvidia/LocateAnything-3B` | NVIDIA — academic/non-profit research only | ~11–35GB VRAM, Ampere+ GPU | Yes (full VLM grounding) | Ruled out — fails both license (non-commercial-only) and hardware (vs. this project's CPU/light-GPU local-model profile: `LFM2.5-1.2B`, `LFM2.5-VL-1.6B`) |
| **YOLO-World** | GPL-v3 (commercial license available on request) | CPU-deployable (ONNX), edge-capable (TFLite/INT8) | Yes — text-prompted, no retraining needed | Best current candidate — matches the actual need (grounding arbitrary planner/user-described targets) and this project's light, CPU-friendly local-model profile far better than a 3B VLM. Confirm commercial license terms before committing if the project ships commercially. |
| RT-DETR / RT-DETRv2 | Apache-2.0 (fully permissive) | GPU-oriented for real-time speed, but ONNX/OpenVINO/CPU deployment documented | No — closed-set detector (COCO/Objects365 classes only) | Cleanest license, lightweight, but only covers generic "person"-class subject boxes (useful for `frame`'s `face_only`/`portrait_headroom` modes), not arbitrary `region_edit`/`background_replace` targets |

**Trigger for adoption:** Revisit once this feature is prioritized. Trial YOLO-World first (best license/capability balance for this project's hardware); fall back to RT-DETR for the narrower "generic subject bbox" case if YOLO-World's license terms don't work out.

**Integration point (whenever a candidate is chosen):** A new registry role (e.g. `"grounding"` or `"detector"`) following the `ModelEntry` pattern already used for `critic`/`cost_router` in `config/registry.py`. Called from `planner/compiler.py` — not exposed to the planner VLM as an op — to resolve semantic targets (e.g. "the face," a `region_edit` prompt) into a verified `BoundingBox` before `Op` construction. This keeps the human-readable plan semantic while making the compiled coordinates deterministic and correct.

---

## Character Focus Framing Mode (First-Subject Auto-Detect)

**Problem:** No `FramingMode` currently auto-detects *where* the subject is. Existing modes (`portrait_headroom`, `face_only`, etc., in `templates/framing.py`) only encode composition rules that the chat VLM applies via prose guesswork over the image — it never receives real subject coordinates. `ops/backends/pil_backend.py:_frame` (via `frame_target_size`, lines ~135-156) does a pure aspect-ratio center-crop with zero subject awareness. A "Character Focus" mode would instead detect the bounding box of the *first* prominent subject (person, animal, or object) and frame around it.

This is a narrower problem than the Open-Vocabulary Detection entry above: no free-text target is needed, just "find the main subject" — so a cheaper class of model/library qualifies (doesn't need YOLO-World/LocateAnything-3B-class open-vocabulary capability).

**Dependency note:** `requirements.txt` pins `opencv-python-headless`, not `opencv-contrib-python-headless`. `cv2.saliency` lives in contrib, so "OpenCV Saliency" below is not already available — it would require a dependency swap, not just an import.

**Candidates considered:**

| Candidate | Year | License | Type | CPU-capable? | Whole subject or face-only risk? | Verdict |
|---|---|---|---|---|---|---|
| U2-Net / U2-Netp | 2020 | Apache-2.0 | Salient-object segmentation net | Yes — u2netp.pth is 4.7MB, CPU-feasible; no official ONNX export (community ports exist) | Whole subject — trained on whole-object saliency masks (DUTS dataset), not face-specific | Strong fit: class-agnostic "find the prominent object," small variant is tiny |
| NanoDet-Plus | 2022 (last release Mar 2023) | Apache-2.0 | Closed-set anchor-free detector | Yes — 1-5MB, NCNN/OpenVINO/MNN support | Whole subject — COCO "person" class box is full-body, not a face box | Fast/tiny but closed-set (COCO classes only) — fine for "person"/"animal", not generic "object" |
| NanoSAM | — | Apache-2.0 | Distilled SAM (MobileSAM→ResNet18) | No — requires NVIDIA Jetson + TensorRT explicitly | Ambiguous — SAM-family models are granularity-ambiguous without a part/whole hint; can return a face-only, torso-only, or full-body mask for the same click depending on internal ranking | Ruled out — hardware mismatch (GPU/Jetson-only, not CPU) |
| EdgeSAM | 2023 | NTU S-Lab License 1.0 (non-standard, research-affiliated — verify commercial terms) | Distilled SAM, mobile-optimized | Yes — 30fps on iPhone 14, 9.6M params | Same SAM granularity ambiguity as NanoSAM/FastSAM/MobileSAM — needs an explicit "whole object" selection strategy, not just "pick a mask" | License needs verification before commercial use; also a segmentation model (heavier than needed for a single bbox) |
| smartcrop.py | — | MIT | Classical heuristic (edge/entropy/saturation, optional face detect) — no ML weights | Yes — trivial, pure Python | Depends on tuning — its optional face-detect boost can bias the crop toward a tight face-only region if weighted too high; default weights favor a broader "interesting area," not strictly a face | Best simplicity fit — purpose-built for "find the crop," zero model weights, but a heuristic not a true detector |
| OpenCV Static Saliency (`StaticSaliencySpectralResidual`, `StaticSaliencyFineGrained`) | — | Apache-2.0 (opencv-contrib) | Classical CV (spectral residual / fine-grained) | Yes — but needs `opencv-contrib-python-headless`, not currently a dependency | Risk of face-only — both algorithms spotlight the highest-contrast region, which on portraits is often just eyes/face rather than the full body | Viable but requires a dependency swap; output is a heatmap, needs thresholding to get a bbox |
| Frequency-Tuned Salient Region Detection (Achanta et al., CVPR 2009) | 2009 | None — public formula, no model weights/library to license | Classical CV (Lab-space contrast vs. Gaussian-blurred mean) | Yes — trivially, ~10 lines of numpy + `cv2.cvtColor`/`cv2.GaussianBlur`, both in base `opencv-python-headless` | Risk of face-only — same contrast-driven fixation as OpenCV Saliency, though the paper's own claim is better full-object boundary preservation than spectral residual | Viable classical fallback, and unlike "OpenCV Static Saliency" needs **no** contrib dependency swap — implement directly against the current pin |
| FastSAM | 2023 | Apache-2.0 | "Segment everything" in one pass, then pick largest/most-central mask for "first object" | Yes, CPU-feasible (lighter than full SAM) | Same SAM-family granularity ambiguity — "everything" mode over-segments, so a naive "pick largest/most-central mask" heuristic can still land on a sub-part (e.g., shirt vs. whole person) | No prompt/class needed to get *a* subject; heavier than U2-Netp/smartcrop for this narrow task |
| MobileSAM | 2023 | Apache-2.0 | Distilled SAM, promptable + automatic mode | Yes — but automatic (no-prompt) mode ~3s/image on CPU (Mac i5) | Same SAM-family granularity ambiguity as above | Correct license/hardware profile but slow for a "first subject" call vs. lighter options |
| YOLO11n-seg | 2024 | AGPL-3.0 (Ultralytics Enterprise license available for commercial use) | Closed-set (COCO 80 classes) detector+segmenter, nano variant | Yes — ONNX/OpenVINO CPU export documented | Whole subject — "person" class box/mask is full-body by definition, most reliable of all candidates on this axis | Best-supported tooling of the closed-set options; directly gives "person"/"animal" class boxes matching the mode's own wording, but needs the same commercial-license check as YOLO-World above |
| MediaPipe Object Detector (EfficientDet-Lite0/Lite2) | — | Apache-2.0 | Closed-set (COCO 80 classes) detector, mobile-optimized | Yes — TFLite, purpose-built for CPU/edge | Whole subject — COCO "person"/animal classes are full-body, same guarantee as YOLO11n-seg | Matches YOLO11n-seg's whole-subject reliability without the AGPL caveat; same `mediapipe` package already named above for face detection, so no new dependency if that's adopted too |
| MediaPipe Image Segmenter (SelfieSegmenter / SelfieMulticlass / DeepLabV3) | — | Apache-2.0 | Segmentation (binary person/bg, or person-parts multiclass, or 21-class DeepLabV3/PASCAL-VOC) | Yes — TFLite, mobile-optimized | Whole subject for person — pixel-accurate mask (SelfieSegmenter/Multiclass), tighter than any bbox since it follows the actual silhouette instead of an axis-aligned box; DeepLabV3 extends to ~20 PASCAL classes (person + several animals: cat, dog, bird, horse, sheep, cow...) but has no generic "object" catch-all the way COCO 80 does | Best paired with, not instead of, MediaPipe Object Detector: use the detector for "is there a subject and what class," derive a tighter bbox from the segmenter's mask extents when the subject is a person; narrower class coverage rules it out as a sole solution for arbitrary "object" subjects |

**Ranked recommendation:**
1. MediaPipe Object Detector — same whole-subject reliability as YOLO11n-seg (COCO "person"/animal classes, full-body by definition) but Apache-2.0, no license caveat, and reuses the `mediapipe` dependency already under consideration for face detection above. For person subjects specifically, pair it with MediaPipe Image Segmenter (SelfieSegmenter/Multiclass) to derive a tighter bbox from the mask extents instead of the detector's raw box — same dependency, no extra cost.
2. YOLO11n-seg — equally reliable whole-subject guarantee; same AGPL-3.0/commercial-license caveat as YOLO-World.
3. U2-Netp — close second on whole-subject reliability, class-agnostic, no license caveat.
4. smartcrop.py — simplest/cheapest to trial, but face-only bias depends on its tunable weights; needs the face-detect signal turned down/off if the goal is whole-person framing.
5. OpenCV Static Saliency / Frequency-Tuned Saliency — viable classical fallbacks, same face-only fixation risk on portraits either way; Frequency-Tuned needs no contrib dependency swap (OpenCV Static Saliency does), so trial it first if avoiding the dependency swap matters more than matching the paper OpenCV ships out of the box.

Ruled out for this narrow use case: NanoSAM (GPU/Jetson-only), EdgeSAM (license needs verification + same SAM granularity ambiguity), FastSAM/MobileSAM (correct license but slower than smartcrop/U2-Netp, plus SAM-family over-segmentation makes "whole subject vs. a sub-part" unreliable without extra logic), NanoDet-Plus (closed-set only, same class as YOLO11n-seg but weaker tooling/ecosystem).

**On "single class YOLO" as a way around the AGPL caveat:** Fine-tuning a person-only detector does not by itself resolve the license caveat attached to YOLO11n-seg/YOLO-World above — the AGPL-3.0 license attaches to Ultralytics' training pipeline/weights regardless of how many classes the result detects. The only inference-time mitigation: export the fine-tuned weights to ONNX or OpenVINO IR and serve them through `onnxruntime`/OpenVINO's runtime instead of importing the `ultralytics` package at all, so this project's runtime dependency is the exported weights, not Ultralytics' AGPL-licensed source. Treat this as a mitigation to verify with counsel, not a settled exemption — same caveat as YOLO11n-seg/YOLO-World, now with the concrete workaround spelled out. A genuinely license-clean single-class detector would instead fine-tune a non-Ultralytics permissive base (YOLOX or the RT-DETR family, both Apache-2.0).

**Face-only risk, generally:** Two distinct failure modes surfaced across candidates — (1) saliency-driven methods (OpenCV Static Saliency, Frequency-Tuned Saliency, smartcrop's face-boost) can fixate on the face specifically since it's usually the highest-contrast/most "interesting" region in a portrait, and (2) SAM-family models (NanoSAM/EdgeSAM/FastSAM/MobileSAM) are granularity-ambiguous by design — the same click/prompt can return a face mask, a torso mask, or a full-body mask depending on internal ranking, with no guaranteed "whole person" output absent extra part/whole selection logic. Only classic whole-object detectors (U2-Net's saliency training set, YOLO/NanoDet/MediaPipe's "person" class) give a reliable whole-subject box out of the box.

**Trigger for adoption:** Revisit once framing precision is prioritized. Trial MediaPipe Object Detector or YOLO11n-seg or U2-Netp first for whole-subject reliability (smartcrop.py only if its face-detect weighting is tuned down first); skip the SAM-family options unless a part/whole selection strategy is designed alongside them.

**Integration point:** `FramingMode.CHARACTER_FOCUS` in `schema/ops.py`; `_FOCUS`/`_RATIO` entries in `templates/framing.py`. No Streamlit UI changes needed since the composition dropdown at `app/main.py:620` (`_framing_opts = [m.value for m in FramingMode]`) derives its options directly from the enum. Unlike the Open-Vocabulary Detection entry above (which routes only through `planner/compiler.py`, bypassing the planner VLM), the detected first-subject bbox for Character Focus should be passed into the planner itself — added as grounding context in the system prompt built by `templates/planner.py` (`_framing_lines`/`_specific_framing_lines`), e.g. "Detected subject bbox: {x, y, w, h}" alongside the existing FRAMING INSTRUCTIONS block — so the chat VLM's `crop` step reasoning is anchored to a real coordinate instead of guessing purely from prose. `pil_backend._frame()` would then also need updating to consume that bbox instead of pure aspect-ratio center-crop.

---

## Op Catalog / Registry + Custom Op Extension Points

**Problem:** op definitions are scattered across five places that must be kept in sync by hand: `schema/ops.py` (`OpName` enum), `ops/validator.py` (`_REQUIRED_PARAMS`, `_PARAM_BOUNDS`), `planner/compiler.py` (`_OP_RISK`, `_OP_DEFAULT_BACKEND`), `templates/planner.py` (prose param docs fed to the LLM), and the backend dispatch tables (`ops/backends/pil_backend.py`, `ops/backends/cv_backend.py`). Nothing enforces agreement between them. This is exactly how the `mask` op ended up broken: it was listed in the planner prompt as `mask: {}` with zero semantic documentation, while its actual backend implementation did something (a full-image solid-color fill) that had no relationship to what an LLM would reasonably infer from the name — see the `mask`/`fill_mask` split fix in `planner/compiler.py`/`ops/backends/pil_backend.py` for the concrete incident.

**Proposed shape:** a single `OpSpec` registry, e.g. `vlm_photo_editor/ops/catalog.py` — one entry per `OpName` holding: params + bounds, required fields, risk tier, default/allowed backends, bbox-eligibility class (size-changing / self-managed-inpaint / generic-confinable), and the exact planner-facing doc string. `validator.py`, `compiler.py`, and `templates/planner.py` would read from this registry instead of maintaining five parallel tables that can drift independently.

**Extension point A — developer-registered ops (trusted):** a `register_op(spec, backend_fn)` call a developer adds from a local module to introduce a new op without editing every core file. Still fully vetted code merged into the repo through normal review; the planner only ever proposes ops already present in the catalog. No new execution-time trust boundary — same risk profile as adding an op today, just centralized.

**Extension point B — planner-authored scripts at plan time:** the LLM itself proposes a small novel script as part of a plan, executed as a MEDIUM/HIGH-risk op. Flagged explicitly as a materially bigger, security-sensitive feature — arbitrary AI-authored code execution — with no sandboxing infrastructure anywhere in this codebase today. This needs its own dedicated design/threat-model document (execution sandbox, resource limits, review/approval flow beyond the existing plan-approval UI, secrets isolation) before any implementation. Do not fold into the catalog work above.

**Trigger for adoption:** once another op or two gets added and the scattered-table pattern causes a second sync bug, or before any custom-op work (extension point A or B) begins.
