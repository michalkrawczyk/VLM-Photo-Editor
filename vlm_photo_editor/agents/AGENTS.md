# agents — Agent Notes

**Role:** All VLM/LLM-powered classes live here. Each file is one agent.
Deterministic logic (compiler, validators, renderers) lives in its own module, not here.

## Import rules
- May import: `schema`, `config`, `models`, stdlib, `langchain_core`, PIL (image encoding only)
- Must NOT import: `imageio`, `ops`, `background`, `recipe`, `secrets`, `prefs`
- TYPE_CHECKING guard on `ImageContainer` (annotation only — avoids runtime imageio import)

## Critical invariants
1. No agent imports `imageio` or `ops` — those are executor-layer concerns.
2. No secrets in prompts. Keys resolved by `build_client()` at call time only.
3. `revise()` may produce a new `plan_id`. Callers tracking lineage record the original.
4. Preferences injected read-only — agents never write back to the prefs store.
5. Stubs (`critic`, `aggregator`) raise `NotImplementedError` with a clear "not implemented until PX" message.

## Files

| File | P-step | Responsibility |
|------|--------|----------------|
| planner.py | P4 | VLM: image + intent → HumanPlan |
| critic.py | P9 | VLM: verify edit quality vs intent |
| aggregator.py | P8 | LLM: summarize deltas into candidate preference rules |
