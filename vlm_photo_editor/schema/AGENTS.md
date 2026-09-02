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
| op_catalog.py | `OpSpec` registry: per-op required params, bounds, risk tier, default backend, bbox-eligibility class, planner doc text — single source of truth read by `ops/validator.py`, `planner/compiler.py`, `templates/planner.py` |
| plan.py | `HumanPlan`, `HumanStep` (stable IDs), `CompilerResult` |
| recipe.py | `Recipe`: op-graph + model + prompt + seed per genAI op |
| prefs.py | `Preferences`, `ExplicitRule`, `LearnedRule`, `PrefsVersion` |
| detection.py | `DetectedSubject`: bbox + label + confidence + source, from a local detector pre-pass |

## Tests
- Location: `tests/unit/test_schema.py`
- Fixtures: `tests/fixtures/schemas/{sample_plan.json, sample_opgraph.json, sample_recipe.json}`
- Key scenarios: valid fixture roundtrips; invalid field types rejected; missing required fields raise `ValidationError`

## Common mistakes

| Wrong | Correct |
|-------|---------|
| `from vlm_photo_editor.ops import ...` inside schema | Schema imports nothing from siblings |
| Store `api_key` field on `Recipe` | Store `model_name` only; key resolved at runtime via `SecretStore` |
| Mutate `HumanStep.id` on plan edit | Discard plan, rerun planner, get new IDs |
