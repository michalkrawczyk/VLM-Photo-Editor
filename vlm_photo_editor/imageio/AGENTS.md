# imageio — Agent Notes

**Role:** Load and save images in all supported formats; never write over the source path.

## Import rules
- May import: `schema`, `config`, stdlib, `Pillow`, `rawpy`, `numpy`
- Must NOT import: `ops`, `planner`, `background`, `recipe`, `secrets`

## Critical invariants
- **Source is immutable:** `save()` must raise `ValueError` if `dest_path == source_path`. Test: `test_imageio.py::test_save_refuses_source_path`.
- **RAW → 16-bit:** `rawpy.imread().postprocess()` must yield a `uint16` numpy array before any Pillow hand-off. Never demosaic directly to 8-bit.
- **ICC preservation:** ICC profile bytes flow through every format conversion and are embedded on save. Never silently drop them.

## Files

| File | Responsibility |
|------|---------------|
| container.py | `ImageContainer`: pixels (numpy array), `bit_depth`, `icc_profile`, `metadata` |
| loaders.py | Format detection; RAW via rawpy; JPG/PNG via Pillow |
| savers.py | `save(container, dest_path)` with source-path guard and naming scheme |

## Tests
- Location: `tests/unit/test_imageio.py`
- Fixtures: `tests/fixtures/images/{sample.jpg, sample.png, sample.nef}`
- Key scenarios: round-trip per format; RAW bit-depth is `uint16`; saving to source path raises; ICC profile survives round-trip

## Common mistakes

| Wrong | Correct |
|-------|---------|
| `PIL.Image.open()` on a `.NEF`/`.CR2` | `rawpy.imread(path).postprocess(output_bps=16)` → `uint16` array |
| Pass the original load path to `save()` | Derive a new path via the naming scheme in `savers.py` |
| Drop `container.icc_profile` on format conversion | Carry bytes through; embed with `Image.save(..., icc_profile=...)` |
| Load RAW to 8-bit for "speed" | Always 16-bit; downconvert only at final export if user requests it |
