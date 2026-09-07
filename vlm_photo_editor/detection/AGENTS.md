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
- **`ready_backends()` vs `available_backends()`:** `available_backends()` is
  package-presence only; `ready_backends()` additionally requires the model path to
  resolve. The main-flow picker offers `ready_backends()`; the Settings expander uses
  `available_backends()` so it can still show an "importable, path not set" badge.
- **Deterministic pre-pass:** detection runs once per plan/revise call, before the
  planner is invoked. It is not exposed to the planner as a callable tool.
- **Bbox always clamped:** every backend clamps its result into `[0, width) x [0, height)`
  before returning `DetectedSubject` — see `_common.py::clamp_bbox`.

## Backend architecture

One file per detector, each exporting a single
`detect(container) -> DetectedSubject | None` function (no class/ABC — each call is
stateless, unlike `background/providers/`'s multi-candidate generators). To add a
new backend:
1. Add a `CharacterFocusBackend` member in `schema/ops.py`.
2. Add a `<name>_backend.py` file with
   `detect(container: ImageContainer) -> DetectedSubject | None`.
3. Add its presence check to `available_backends()`, a `_BACKEND_PATH_ATTR` entry,
   and its dispatch branch in `detect_subject()` — all in `__init__.py`.
4. Add its model-path field to `AppSettings` (`config/settings.py`).

## Files

| File | Responsibility |
|------|---------------|
| `__init__.py` | `available_backends()`, `ready_backends()`, `detect_subject(container, backend)` |
| `_common.py` | `clamp_bbox()`, `to_rgb_uint8()` — shared by all backends |
| `mediapipe_backend.py` | MediaPipe `ObjectDetector` (TFLite) |
| `yolo_onnx_backend.py` | YOLO via `onnxruntime` — manual letterbox/NMS |
| `u2netp_backend.py` | U2-Netp salient-object mask via `onnxruntime` → largest component bbox |

## Tests
- Location: `tests/unit/test_p13_character_focus.py`
- Key scenarios: `available_backends()` reflects installed packages only;
  `ready_backends()` additionally drops backends with no resolvable model path (and
  the main-flow picker hides them); each backend's bbox is clamped inside image
  bounds; missing model path raises with the setting name in the message.

## Common mistakes

| Wrong | Correct |
|-------|---------|
| Import `mediapipe`/`onnxruntime` at module top level | Import lazily inside `detect()` |
| Fall back to another backend when the configured one fails | Raise `ValueError`; caller (UI) surfaces the error |
| Return an unclamped bbox | Always pass through `clamp_bbox()` |
| Call `detect_subject()` for `backend="off"` | Caller skips detection entirely when off |
