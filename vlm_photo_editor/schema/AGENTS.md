# schema — Agent Notes

**Role:** All Pydantic contracts for the pipeline; the root dependency — every other module imports from here.

## Import rules
- May import: stdlib, `pydantic`
- Must NOT import: any sibling module (`config`, `imageio`, `ops`, `secrets`, etc.) — schema is the root dep; a sibling import creates a cycle

## Critical invariants
- **Stable step-IDs:** `HumanStep.id` is set once at plan creation and never mutated mid-session. Recompile from scratch if the plan changes.
- **No key storage in Recipe:** `Recipe` stores model name only; never a raw API key or bearer token.
- **Contract freeze:** changing a field type or removing a field requires updating all dependents before committing.

## Files

| File | Responsibility |
|------|---------------|
| ops.py | `Op`, `OpGraph`, `OpName` enum, `Backend` enum, `RiskTier` enum |
| op_catalog.py | `OpSpec` registry: per-op required + **optional** params, bounds, risk tier, default backend, bbox-eligibility class, planner doc text — single source of truth read by `ops/validator.py`, `planner/compiler.py`, `templates/planner.py` |
| plan.py | `HumanPlan` (incl. optional `diagnosis`, display-only), `HumanStep` (stable IDs), `CompilerResult` |
| recipe.py | `Recipe`: op-graph + model + prompt + seed per genAI op; `schema_version` (`RECIPE_SCHEMA_VERSION`, 2) — absent on disk = v1, migrated by `RecipeStore.load` |
| prefs.py | `Preferences` (incl. `dismissed`: normalized text of dismissed learned rules), `ExplicitRule`, `LearnedRule`, `PrefsVersion` |
| detection.py | `DetectedSubject`: bbox + label + confidence + source, from a local detector pre-pass |
| report.py | `StepCheck` (one Critic stage-1 before/after check) + `ImageReport` + `ExifSummary`: deterministic image measurements (luma percentiles, clipping, cast, sharpness, noise, tilt, whitelisted EXIF) computed by `analysis/` and passed into the planner |
| batch.py | `BatchImageRecord` (per-image state for P11 batch runs), `ImageStatus` enum. `intent: str = ""` is an optional per-image instruction override (Mode B); `""` falls back to the batch-wide intent |

## Tests
- Location: `tests/unit/test_schema.py`
- Fixtures: `tests/fixtures/schemas/{sample_plan.json, sample_opgraph.json, sample_recipe.json}`
- Key scenarios: valid fixture roundtrips; invalid field types rejected; missing required fields raise `ValidationError`

## Notes

- **Closed param contract (S-C1):** `OpSpec.optional_params` lists the non-required
  keys a backend actually reads. `ops/validator.py` rejects any `Op.params` key
  outside `required ∪ optional ∪ {invert, focus_x, focus_y, focus_w, focus_h}` (the
  compiler-injected set). Adding a new param a backend reads means adding it to the
  op's `optional_params` — otherwise the op fails validation at plan time.

## Common mistakes

| Wrong | Correct |
|-------|---------|
| `from vlm_photo_editor.ops import ...` inside schema | Schema imports nothing from siblings |
| Store `api_key` field on `Recipe` | Store `model_name` only; key resolved at runtime via `SecretStore` |
| Mutate `HumanStep.id` on plan edit | Discard plan, rerun planner, get new IDs |
