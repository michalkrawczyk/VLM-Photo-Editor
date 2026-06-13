# ops — Agent Notes

**Role:** Deterministic edit engine — validate, route, and apply `Op` instances to an `ImageContainer`.

## Import rules
- May import: `schema`, `config`, `imageio`, stdlib, `numpy`, `Pillow`, `opencv-python-headless`, `scipy`
- Must NOT import: `planner`, `background`, `secrets`, `prefs`

## Critical invariants
- **Validate before execute:** every `Op` passes through `validator.py` before `executor.py` dispatches it. Unknown `OpName` or out-of-bounds params → `ValueError`, no execution.
- **Region isolation:** a bbox region edit must assert that pixels outside the mask are byte-identical before returning. Test: `test_ops.py::test_region_edit_isolates_pixels`.
- **Backend stubs raise:** `genai` and `photoshop` backends in `stubs.py` raise `NotImplementedError` — import only under the active policy.

## Files

| File | Responsibility |
|------|---------------|
| executor.py | `Executor.apply(container, opgraph) → ImageContainer` — dispatch loop |
| validator.py | Reject unknown ops and out-of-bounds params with clear error messages |
| mask.py | `bbox → region mask`; subject-pixel freeze assertion helper |
| backends/pil_backend.py | crop, rotate, white-balance, exposure, denoise via Pillow |
| backends/cv_backend.py | Ops that benefit from OpenCV (bilateral denoise, edge detection) |
| backends/stubs.py | genAI and Photoshop backend stubs (raise `NotImplementedError`) |

## Tests
- Location: `tests/unit/test_ops.py`
- Fixtures: `tests/fixtures/images/sample.jpg`, `tests/fixtures/schemas/sample_opgraph.json`
- Key scenarios: valid op-graph applies correctly; unknown op raises; out-of-bounds param raises; bbox region edit changes only masked pixels

## Common mistakes

| Wrong | Correct |
|-------|---------|
| Call backend directly without going through `validator.py` | Always `Executor.apply()` which runs validator first |
| Import `stubs.py` unconditionally | Import only when `policy.backend == Backend.GENAI` or `Backend.PHOTOSHOP` |
| Return original container mutated in-place | Return a new `ImageContainer`; originals are immutable |
| Skip the region-isolation assertion | `mask.py` assertion must run on every region edit |
