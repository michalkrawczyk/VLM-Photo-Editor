# background — Agent Notes

**Role:** genAI background pipeline — generate candidates, composite, color/grain-match, and gate on seam quality.

## Import rules
- May import: `schema`, `config`, `imageio`, `ops`, stdlib, `numpy`, `scipy`, `scikit-image`, `replicate`
- Must NOT import: `planner`, `secrets` (keys resolved externally before call), `prefs`

## Critical invariants
- **Subject pixels frozen:** after compositing, assert that every pixel outside the mask is byte-identical to the input. Test: `test_background.py::test_subject_pixels_unchanged`. This is a hard assertion, not a warning.
- **Seed/model/prompt stored:** every candidate generation records `model`, `prompt`, and `seed` in the `Recipe`. No genAI op without a determinism record.
- **Seam gate:** if the seam metric exceeds threshold after seed re-roll, flag the result for manual review — do not silently pass a bad composite.
- **N candidates returned:** generator must return exactly N candidates (different seeds); caller picks one.

## Files

| File | Responsibility |
|------|---------------|
| generator.py | Generate N candidates via replicate inpainting; store seed/prompt/model per candidate |
| composite.py | LAB mean/std color transfer from border ring; grain/noise match to subject; feathered seam blend |
| quality.py | Edge-gradient seam metric; seed re-roll on failure; flag-for-manual fallback |

## Tests
- Location: `tests/unit/test_background.py`
- Fixtures: `tests/fixtures/images/sample.jpg` + a mock replicate client
- Key scenarios: subject pixels unchanged after composite; seam metric gates on threshold; N candidates returned; chosen candidate reproducible from stored seed

## Common mistakes

| Wrong | Correct |
|-------|---------|
| Modify pixels outside the mask during composite | Apply color/grain transfer only inside the masked region |
| Skip seed storage when a candidate is accepted | Always store seed/model/prompt before returning any candidate |
| Pass the seam metric check with a soft warning | Hard gate: re-roll seed, then flag for manual if still failing |
| Color transfer in RGB space | Convert to LAB first (`skimage.color.rgb2lab`) for perceptually correct transfer |
