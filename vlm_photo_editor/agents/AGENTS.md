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
3. `revise()` gets original intent + previous plan + feedback and a system-prompt REVISION RULE (feedback overrides framing/subject anchoring); an unchanged result is re-asked once. It may produce a new `plan_id`. Callers tracking lineage record the original.
3b. `adapt()` plans one image following a plan approved on another (batch Mode A): the reference supplies methodology, every parameter is re-derived for the new image (ADAPTATION RULE); steps may differ.
4. Preferences injected read-only — agents never write back to the prefs store.
5. Stubs (`critic`, `aggregator`) raise `NotImplementedError` with a clear "not implemented until PX" message.

## Files

| File | P-step | Responsibility |
|------|--------|----------------|
| planner.py | P4 | VLM: image + intent (+ optional `DetectedSubject`, `ImageReport`) → HumanPlan. Image sent ≤1568 px long edge, sRGB, no contrast stretch; the MEASUREMENTS block rides in the user message, its static rules in the system prompt only when a report is passed |
| critic.py | P9 | Critic: stage 1 = failed deterministic `StepCheck`s (from `analysis/critic_checks.py`, computed by the app) fail without a VLM call; stage 2 = VLM sees before/after + plan + measurements and answers `verdict` pass/fail/uncertain (+ at-fault `step_id`); parse/API error = uncertain pass, never silent |
| aggregator.py | P8 | LLM: summarize deltas into candidate preference rules |
