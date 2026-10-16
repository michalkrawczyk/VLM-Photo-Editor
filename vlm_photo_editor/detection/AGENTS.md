# detection — Agent Notes

**Role:** Local, zero-API-cost subject detection — find the primary subject's bounding
box before planning, for use as framing/crop context.

## Import rules
- May import: `schema`, `config`, `imageio`, stdlib, `numpy`
- May import detector SDKs lazily inside backend files (`mediapipe`, `onnxruntime`, `opencv`)
- Must NOT import: `planner`, `agents`, `background`, `secrets`

## Critical invariants
- **No silent fallback:** a backend whose package is installed but whose model path
  (`AppSettings.*_model_path`) is unset/missing raises `ValueError` naming the
  missing setting. Never falls through to another backend.
- **Empty result ≠ misconfiguration (DET-P2):** a detector that ran cleanly and
  found nothing returns `None` (`detect()` / `detect_subject()` are
  `-> DetectedSubject | None`). `ValueError` is reserved for misconfiguration
  (missing model path, unknown/off backend). Callers treat `None` as "plan
  without subject context" — the default, gracefully-handled path.
- **Model-path resolution (`config/settings.py::_path_setting`):** each
  `AppSettings.*_model_path` resolves `<NAME>_MODEL_PATH` (`MEDIAPIPE_MODEL_PATH` /
  `YOLO_ONNX_MODEL_PATH` / `U2NETP_MODEL_PATH`) from the environment, then from `.env`
  (read via `dotenv_values`, so co-located API keys never enter `os.environ`), then —
  `yolo_onnx` only — the bundled `infer_models/yolo/yolo26s.onnx` if that file exists,
  else `None`. Still no auto-download and still no silent fallback to another backend.
- **Model vs backend:** `CharacterFocusBackend` is the runtime family (mediapipe /
  yolo_onnx / u2netp). A `DetectorModel` (`schema/detection.py`) is one selectable model:
  `id`, `backend`, `path`, `labels` (`None` = class-agnostic), `origin`, optional
  `layout`/`input_size`/`conf_threshold`, `invalid_reason`. `registry.list_models()` builds
  them fresh each call from three sources: **legacy** (the three `AppSettings.*_model_path`
  slots; id == backend name), **discovered** (`AppSettings.detector_models_dir`, default
  `infer_models/<dir>/` holding one `.onnx`/`.tflite`), **user** (paths in
  `AppSettings.detectors_file`, default `~/.config/vlm_photo_editor/detectors.json`; paths
  only, no secrets). A discovered file that is already a legacy slot's path is skipped.
- **Readiness:** `available_backends()` = package importable only. `ready_models()` =
  package importable AND `invalid_reason is None` AND path set. Invalid models stay in
  `list_models()` with their reason (Settings shows it) but are never offered in the main
  flow and `detect_subject()` raises their `invalid_reason` as `ValueError` (no silent
  fallback). Legacy slots skip the file-exists check (pre-registry contract);
  discovered/user models do not.
- **Backend inference for scanned/user files:** `.tflite` → mediapipe; `.onnx` + sibling
  `classes.txt` → yolo_onnx; `.onnx` without `classes.txt` needs `model.json
  {"backend": "u2netp"}` (saliency) or is invalid.
- **Vocabulary:** yolo_onnx = sibling `classes.txt` (one name per line, 0-based line
  index == class id; interior blanks kept, trailing dropped). mediapipe = labels zipped in
  the tflite metadata, else a sibling `classes.txt`, else `None`. u2netp = `None`.
  **No person/human class is required** — a model without one is allowed; the UI warns
  (“may not work for portraits / human-oriented edits”). `face_only` still needs a `face`
  label (`model_has_label(id, "face")`).
- **Target classes:** `detect_subject(container, model_id, target_labels=None)`; `None`/empty
  = every class (default — no behavior change vs. before the registry). Names match
  case-insensitively; an unknown name or targets on a class-agnostic model raise
  `ValueError`. yolo restricts the class-score columns before argmax; mediapipe uses
  `category_allowlist`; u2netp has no targets.
- **YOLO output layouts (`model.json` `"layout"`):** `yolov8` (default, `(N, 4+C)`, auto-
  transposed), `yolov5` (`(N, 5+C)`, score = objectness x class), `nms` (NMS-baked rows
  `x1,y1,x2,y2,score,class_id`, no extra NMS). Unknown value → model invalid. Input size
  comes from `model.json` `input_size`, else the ONNX input's square static shape, else 640.
  Class-count mismatch raises with a hint naming the `layout` key. Unsupported: segmentation
  heads, multi-output graphs.
- **Legacy API** (`ready_backends()`, `detector_labels()`, `detector_has_label()`,
  `requires_classes_txt()`): thin wrappers over the legacy-slot model ids; new code uses
  `ready_models()`, `model_labels()`, `model_has_label()`, `model_has_person()`,
  `model_person_labels()`.
- **Deterministic pre-pass:** detection runs once per plan/revise call, before the
  planner is invoked. It is not exposed to the planner as a callable tool.
- **Bbox always clamped:** every backend clamps its result into `[0, width) x [0, height)`
  before returning `DetectedSubject` — see `_common.py::clamp_bbox`.

## Backend architecture

One file per runtime family, each exporting `detect(container, model: DetectorModel[,
target_labels])` (no class/ABC — each call is stateless, unlike `background/providers/`).
To add a **model** for an existing family: drop a folder into `infer_models/` or use
Settings → Detector models → Add (no code). To add a new **family**:
1. Add a `CharacterFocusBackend` member in `schema/ops.py`.
2. Add `<name>_backend.py` with `detect(container, model, target_labels) -> DetectedSubject | None`.
3. Register it in `registry.py` (`_BACKEND_PACKAGE`, label resolution in `_resolve_labels`,
   optionally `_LEGACY_PATH_ATTR` + an `AppSettings` path for a legacy slot), add its
   presence check to `available_backends()` and its dispatch branch in `detect_subject()`.

## Files

| File | Responsibility |
|------|---------------|
| `__init__.py` | `detect_subject()`, `available_backends()`, `install_backend_deps()`, legacy wrappers, re-exports of the registry API |
| `registry.py` | `list_models()`, `ready_models()`, `get_model()`, `model_labels()`, `model_has_label()`, `model_has_person()`, `add_user_model()`, `remove_user_model()` — scan + manual registration |
| `_common.py` | `clamp_bbox()`, `to_rgb_uint8()`, `load_class_labels()`, `has_human_label()`, `human_labels()`, `resolve_target_ids()` — shared by all backends |
| `mediapipe_backend.py` | MediaPipe `ObjectDetector` (TFLite) |
| `yolo_onnx_backend.py` | YOLO via `onnxruntime` — manual letterbox/NMS |
| `u2netp_backend.py` | U2-Netp salient-object mask via `onnxruntime` → largest component bbox |

## Tests
- Location: `tests/unit/test_p13_character_focus.py` (extend it; use the `registry_env`
  fixture + `_model_dir()` helper for registry/scan tests).
- Key scenarios: `available_backends()` reflects installed packages only; legacy
  `ready_backends()` needs a resolvable path (+ `classes.txt` for yolo_onnx, person class
  NOT required); scan/manual-add/remove; invalid models listed but not ready; each backend's
  bbox is clamped; target filtering picks a lower-scoring target over a higher-scoring other
  class; yolov8/yolov5/nms layouts; `face_only` absent from Composition unless the active
  model has a `face` label; no-person warning in the UI.

## Common mistakes

| Wrong | Correct |
|-------|---------|
| Import `mediapipe`/`onnxruntime` at module top level | Import lazily inside `detect()` |
| Fall back to another backend/model when the configured one fails | Raise `ValueError`; caller (UI) surfaces the error |
| Require a person class, or silently drop an unknown target class | Allow any model; warn in the UI; raise on an unknown target |
| Return an unclamped bbox | Always pass through `clamp_bbox()` |
| Call `detect_subject()` for `backend="off"` | Caller skips detection entirely when off |
