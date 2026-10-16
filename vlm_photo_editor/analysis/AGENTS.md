# analysis — Agent Notes

**Role:** Deterministic image measurements (`ImageReport`) handed to the planner as ground
truth, so the VLM stops guessing exposure/cast/tilt numbers from vibes. No VLM, no network,
no RNG — same pixels in, same report out.

## Import rules
- May import: `schema`, `imageio` (`ImageContainer` under `TYPE_CHECKING` only), stdlib,
  `numpy`, `opencv-python-headless` (lazy), `Pillow` (EXIF parsing only)
- Must NOT import: `agents`, `planner`, `ops`, `background`, `secrets`, `preferences`
- Callers (app/pipeline) compute the report and pass it into `Planner`; `agents/` never imports
  this module (same pattern as `detection/` → `DetectedSubject`).

## Critical invariants
- **Convention parity with `ops`:** `suggested_wb_temperature` assumes the Lightroom convention
  and the `1 ± 0.5·dev` multipliers of `pil_backend._white_balance` (6500 K neutral, bounds
  1000–20000). `test_analysis.py` applies the suggestion through the real `Executor` and checks
  the cast is gone — change both sides together.
- **EXIF is a whitelist** (`ExifSummary`): ISO, exposure time, f-number, focal length, WB mode,
  exposure bias. Never GPS, serials, owner or maker notes. Unreadable EXIF ⇒ all-`None`, never raises.
- **Fixed analysis scale:** stats run on a ≤1024 px long-edge copy so sharpness is comparable
  across resolutions; noise is the exception (native-res centre crop — downscaling averages
  noise away).
- **Gray-world is a heuristic:** a scene dominated by one colour (forest, sunset) reads as a
  cast. The prompt treats `suggested_wb_temperature` as a hint, not a command.
- **Tilt sign:** `tilt_deg` > 0 = visual counter-clockwise lean; level with `rotate(-tilt_deg)`.

## Files

| File | Responsibility |
|------|---------------|
| image_report.py | `compute_report(container) -> ImageReport` |
| exif.py | `parse_exif(raw_bytes) -> ExifSummary` |
| critic_checks.py | `check_edit(op_graph, before, after) -> list[StepCheck]`: Critic stage 1. Expectations come from the compiled ops (net EV sign -> luma, WB direction -> R/B, tone highlights/shadows -> P95/P5 when no exposure/contrast/end-point term blurs it, denoise -> noise, levelling rotate -> tilt), never from model prose. Global ops only; tone/colour skipped when the frame is reshaped. Callers compute the two reports and pass the checks into `Critic.verify` |

## Tests
- Location: `tests/unit/test_analysis.py` (synthetic arrays only)
