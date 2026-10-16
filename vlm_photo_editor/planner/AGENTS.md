# planner — Agent Notes

**Role:** Deterministic compilation layer. HumanPlan → validated OpGraph. No LLM calls.

## Import rules
- May import: `schema`, `config`, `ops.validator`, stdlib
- Must NOT import: `agents`, `imageio`, `background`, `recipe`, `secrets`

## Critical invariants
1. `step_id` never mutated. Compiler copies `HumanStep.step_id` directly to each Op.
2. Compiler is deterministic. Same plan + mode → same OpGraph every time.
3. `allowed_ops_for_mode` gates validation — never bypass it.
4. Unknown mode → `KeyError` (caller bug, let propagate). Bad plan → `CompilerError`.
5. `repair.py`: `compile_with_repair` is the one bounded compile->revise loop (single-image app
   flow and batch planning; `edit_flow`'s graph keeps its own crop routing and is not run by the
   app). Only `CompilerError.repairable` failures are retried; PS/GenAI/mode errors are
   environmental and surface at once. Budget = `settings.max_crop_retries` (now covers every
   repairable error, not just crops). Each revision is a `RepairNote`, shown in the UI.
   `compile_checked` also runs `check_plan_sanity` (net global |ev| <= 4, rotate within 20 deg
   of a right angle) as a repairable error. Plan-time only: these caps are deliberately not in
   `PARAM_BOUNDS`, which also validates saved recipes on replay.
6. `op_params` shorter than `op_names` is padded with empty dicts; the validator then
   catches missing required params with a clear error.
