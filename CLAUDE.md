# VLM Photo Editor — Claude Instructions

## Project Mission

Photo editing app powered by a VLM: propose a human-readable plan → user approves → deterministic executor runs it. Backgrounds may use genAI; everything else uses ordinary imaging libs. Originals are never altered.

**One-line architecture:** Planner (VLM) → human-readable plan → user approval → Compiler → validated OpGraph → Executor (deterministic code + optional genAI + optional Photoshop) → Recipe (non-destructive, replayable). An optional Critic verifies results.

**Non-negotiable principles:**
1. **Originals are sacred.** Saves always write a new file. Writing over the source is a bug.
2. **Keys are secret.** Never in code, recipes, sidecars, logs, prompts, or session state. Resolution: env → OS keyring → gitignored `.env`. Keys reach only the provider client at call time; UI shows them masked; redaction filter scrubs logs. Recipes store model name only.
3. **Plan before action.** Human-readable plan is source of truth. Compiled ops link back by stable step-ID; never silently rewritten.
4. **Human in the loop (manual mode).** Nothing executes until user explicitly approves. Change requests regenerate the plan and re-prompt — loop until approval.
5. **Deterministic and reproducible.** Edits are a replayable recipe; generative steps record model + prompt + seed.
6. **Subject pixels frozen** during background generation — only the masked region changes.
7. **Contracts before behavior.** Define schemas first; don't change a contract without updating all dependents.
8. **Planner ↔ Executor parity.** Planner may only propose ops the executor can run under the active policy (Auto / PS-strict / No-PS).
9. **Photoshop is optional, never required.** One backend behind specific ops, not a dependency.

**How to work on this project:**
- Follow `plans/photo_editor_build_plan.md` in order. DoD checkboxes are a gate, not a suggestion.
- If a request conflicts with a principle above, stop and flag it — don't quietly reinterpret.
- Prefer the boring, deterministic path. Use genAI/Photoshop only where imaging libs genuinely can't do the job.
- Make the invisible inspectable: plans, compiled ops, recipes, and learned preferences must be viewable and editable.
- Fail loudly and safely. Reject invalid plans/params with clear errors; never execute something unvalidated.

---

## Communication Style

Terse, but focused on task always. Stay on-task every response — no drift. Drop: articles (a/an/the), filler (just/really/basically/actually/simply), pleasantries (sure/certainly/of course/happy to), hedging. Fragments OK. Short synonyms (big not extensive, fix not "implement a solution for"). Technical terms exact. Code blocks unchanged. Errors quoted exact.

Pattern: `[thing] [action] [reason]. [next step].`

Not: "Sure! I'd be happy to help you with that. The issue you're experiencing is likely caused by..."
Yes: "Bug in auth middleware. Token expiry check use `<` not `<=`. Fix:"

Exceptions (write full sentences): destructive/irreversible actions, multi-step sequences where fragment order risks misread.

**Thinking/Reasoning blocks:** Same rules apply — terse, no filler, no hedging. Direct deliberation, not narrated exploration ("let me think...", "I should consider...", "hmm, actually...").

---

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Testing

Before creating new test units, check if tested methods can be added to existing pipelines. Markers: `slow` (long-running), `integration` (requires full pipeline).

Fewer test functions, broader coverage. Use `@pytest.mark.parametrize` — never `for` loops. Merge related assertions (schema + round-trip + error case) into one test.

---

## Git Commits

Conventional Commits. Subject ≤50 chars (hard cap 72). Imperative mood. No trailing period. Format: `<type>(<scope>): <summary>`. Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`, `build`, `ci`, `style`, `revert`. Body only for non-obvious why, breaking changes, migration notes, `Closes #N`. No AI attribution or emoji.

---

## Tech Stack

See [agent_notes/stack.md](agent_notes/stack.md) for full stack and rationale. Required: Pydantic≥2.7, structlog≥24.0, rawpy (not PIL) for RAW, LangChain+LangGraph, replicate≥0.30, Streamlit, anyio≥4.3.

---

## Architecture Rules

Layer locations: [agent_notes/structure.md](agent_notes/structure.md). Strict boundaries: `schema/` imports nothing from siblings; `planner/` never imports `imageio/`/`ops/`; `imageio/` never overwrites source; `secrets/` RedactionProcessor on every log sink.

---

## Common Mistakes

| Wrong | Correct |
|-------|---------|
| Log or print API key anywhere | Route all output through structlog with RedactionProcessor active |
| Store API key in Recipe JSON | Store model name only; key resolved at runtime via SecretStore |
| Overwrite source image on save | Always write to new path; original is immutable |
| Execute Op without schema validation | Pass ops through Executor.apply() which validates against OpGraph |
| Use PIL for RAW files | Use rawpy → 16-bit numpy array; hand to Pillow only for save |
| Mutate HumanPlan step-IDs mid-session | Step-IDs are stable; recompile from scratch if plan changes |
| Skip seed storage for genAI ops | Always store model + prompt + seed in Recipe for reproducibility |
| Import from siblings inside `schema/` | Schema is root dep; it imports nothing from siblings |

---

## Reference Documentation

**Stack & Rationale:** [agent_notes/stack.md](agent_notes/stack.md)  
**Project Structure:** [agent_notes/structure.md](agent_notes/structure.md)  
**Product Description:** [agent_notes/description.md](agent_notes/description.md)  
**Build Plan (P0–P10):** [plans/photo_editor_build_plan.md](plans/photo_editor_build_plan.md)  
**Future/Deferred:** [agent_notes/future_improvements.md](agent_notes/future_improvements.md)  
**Codebase Navigation:** invoke `Skill("codebase-navigation")` before any grep/find/search operation. Run `python agent_notes/generate_module_map.py` to regenerate module map.
