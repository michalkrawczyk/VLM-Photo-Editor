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
5. `op_params` shorter than `op_names` is padded with empty dicts; the validator then
   catches missing required params with a clear error.
