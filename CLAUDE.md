# VLM Photo Editor — Claude Instructions

## Mission

Photo editing app powered by a VLM: propose a human-readable plan → user approves → deterministic executor runs it. Backgrounds may use genAI; everything else uses ordinary imaging libs. Originals are never altered.

For a photographer/editor who wants fast, explainable, reversible edits — not a black box. Four accept modes control automation level: `manual` always prompts; `auto_low`/`auto_medium` skip approval by risk tier (LOW / LOW+MEDIUM); `full_auto` executes with no pre-execution gate at all, including genAI ops — safe because subject pixels are frozen and saves are non-destructive, so a bad result only costs a rerun (bounded by a per-run genAI ceiling; batch `full_auto` still requires post-run review before "Save All").

**One-line architecture:** Planner (VLM) → human-readable plan → user approval → Compiler → validated OpGraph → Executor (deterministic code + optional genAI + optional Photoshop) → Recipe (non-destructive, replayable). An optional Critic verifies results.

**Non-goals:** video/motion content, multi-user/team collaboration or cloud sync, mobile/web-hosted deployment, print-production color-managed workflows.

**Maturity:** mature, not scaffold-stage. Build plan (`plans/photo_editor_build_plan.md`) spans P0–P13, most DoD checkboxes done — count the boxes there, don't trust a number quoted here. Follow it in order — DoD checkboxes are a gate, not a suggestion.

### Non-negotiable principles

1. **Originals are sacred.** Saves always write a new file. Writing over the source is a bug.
2. **Keys are secret.** Never in code, recipes, sidecars, logs, prompts, or session state. Resolution: env → OS keyring → gitignored `.env`. Keys reach only the provider client at call time; UI shows them masked; redaction filter scrubs logs. Recipes store model name only.
3. **Plan before action.** Human-readable plan is source of truth. Compiled ops link back by stable step-ID; never silently rewritten.
4. **Human in the loop (manual mode).** Nothing executes until user explicitly approves. Change requests regenerate the plan and re-prompt — loop until approval.
5. **Deterministic and reproducible.** Edits are a replayable recipe; generative steps record model + prompt + seed.
6. **Subject pixels frozen** during background generation — only the masked region changes.
7. **Contracts before behavior.** Define schemas first; don't change a contract without updating all dependents.
8. **Planner ↔ Executor parity.** Planner may only propose ops the executor can run under the active policy (Auto / PS-strict / No-PS).
9. **Photoshop is optional, never required.** One backend behind specific ops, not a dependency.

### Working notes

- When a file's path is already known, read it directly — don't use an Explore agent (it summarizes, losing precision). See "Code search order" under `agent_notes/` below for locating unknown symbols.
- If a request conflicts with a principle above, stop and flag it — don't quietly reinterpret.
- Prefer the boring, deterministic path. Use genAI/Photoshop only where imaging libs genuinely can't do the job.
- Make the invisible inspectable: plans, compiled ops, recipes, and learned preferences must stay viewable and editable.
- Fail loudly and safely. Reject invalid plans/params with clear errors; never execute something unvalidated.

---

## Precedence

`session instruction > CLAUDE.md > agent_notes/ > defaults.`

---

## Challenge

Plan given ≠ plan accepted. Applies to plans, solutions, theories, claims, analyses — yours and the user's.

Before executing or agreeing:
- Name the weakest step/assumption/claim and why it's weakest
- Name what breaks if it's wrong
- Name the cheaper alternative if one exists

Format: `Weak point: [what] → [consequence]. Alternative: [what].`
Max 3, ranked by cost. Weak point exists → state it, always. Silence = you found none, and you own that.

Flag explicitly: irreversible steps, data loss paths, unbounded scope, unverifiable success criteria,
unstated assumptions, work duplicating something already in repo, reasoning that holds only in the happy path.

Disagreement is not delay: state objection once, then proceed with user's choice unless T3-gated.

---

## Done Gate

Task complete → read [agent_notes/done_gate.md](agent_notes/done_gate.md), run that tier.
Tiers: T0 docs · T1 any code · T2 behavior change · T3 schema/migration/public API/dep/config.
T1 minimum: `bash agent_notes/utility_scripts/run_checks.sh` → every BLOCK row PASS **except the
known-red `ruff` row** (48 pre-existing errors on a clean tree, 1 auto-fixable). Interim pass
condition: no new ruff errors in files your diff touched — state that, never claim green.
Baseline table: `done_gate.md`.
Scoped runs: `[PATH ...]`, `-k EXPR`, `-m MARKER`, `--ignore PATH`, `--short [N]` (tails pytest output only — Summary table and exit code stay intact). Full list: `done_gate.md`.
pydocstyle is WARN-only, never blocks. Any `SKIP` row → tool not installed, say "unverified".
T3 requires human confirm before commit, and `--full` green.
Report: `Changed: … | Ran: cmd → result | Assumptions: … | Not done: …`
No green claim without command output. Every changed line traces to request.

---

## Stuck

Same error 3x → stop. Report diagnosis, attempts, what's needed.
Never: skip/xfail, `# type: ignore`, `except: pass`, mock the failure, weaken assertion, delete test, `--no-verify`.

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

Formatter output wins over local style.

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

## Subagents

Before delegating: read [agent_notes/subagents.md](agent_notes/subagents.md).
Never delegate: work needing this conversation's accumulated context · write/architecture/API
decisions · the Done Gate · commits. Known-path reads are cheaper direct — don't brief an agent.
A subagent's "tests pass" never satisfies T1–T3. Rerun the gate yourself.
Report is a claim, not a fact — open the cited file:line before acting on it.
Report delegation in your summary: `Delegated: [what] → [what came back].`

---

## Testing

Before writing a test: read [agent_notes/testing.md](agent_notes/testing.md).
Extend existing coverage > new file. `@pytest.mark.parametrize` — never `for` loops.
Markers (`pyproject.toml`): `slow` · `integration` · `e2e`. `addopts` excludes **e2e** by default,
not slow; the fast gate run is an explicit `pytest -m "not slow"`.
Session-written scripts → `.tmp_scripts/` (gitignored), never imported by the package.

---

## Git Commits

Before any commit: read [agent_notes/git.md](agent_notes/git.md).
Conventional Commits: `<type>(<scope>): <summary>`, subject ≤50 chars (hard cap 72), imperative, no
trailing period. Never commit secrets, `.env`, generated files (`agent_ignore/`), binaries,
`.tmp_scripts/`. No AI attribution or emoji. Never `--no-verify`.

---

## Architecture & Stack

Layer locations and file tree: [agent_notes/structure.md](agent_notes/structure.md). Strict boundaries: `schema/` imports nothing from siblings; `planner/` never imports `imageio/`/`ops/`; `imageio/` never overwrites source; `secrets/` `RedactionFilter` on every log sink (stdlib `logging.Filter`, not a structlog processor — see `agent_notes/stack.md` for an open caveat on structlog-routed log calls).

Required deps: Pydantic≥2.7, structlog≥24.0, rawpy (not PIL) for RAW, LangChain+LangGraph, replicate≥0.30, Streamlit, anyio≥4.3. Full stack + rationale: [agent_notes/stack.md](agent_notes/stack.md).

Per-module invariants, import rules, common mistakes: `vlm_photo_editor/<module>/AGENTS.md`, where present (9/15 modules — see `agent_notes/structure.md` for current coverage).

### Common Mistakes

| Wrong | Correct |
|-------|---------|
| Log or print API key anywhere | Route all output through logging with `RedactionFilter` active |
| Store API key in Recipe JSON | Store model name only; key resolved at runtime via SecretStore |
| Overwrite source image on save | Always write to new path; original is immutable |
| Execute Op without schema validation | Pass ops through Executor.apply() which validates against OpGraph |
| Use PIL for RAW files | Use rawpy → 16-bit numpy array; hand to Pillow only for save |
| Mutate HumanPlan step-IDs mid-session | Step-IDs are stable; recompile from scratch if plan changes |
| Skip seed storage for genAI ops | Always store model + prompt + seed in Recipe for reproducibility |
| Import from siblings inside `schema/` | Schema is root dep; it imports nothing from siblings |

---

## agent_notes/

Project notes bundle — dir name is `agent_notes/`, not `.agent_notes/` (established convention, kept as-is). One concept per file. Read `agent_notes/index.md` at task start for the full map; terse version below.

**Read-at-start:** `agent_notes/commands.md` (verified setup/run/test/lint/typecheck commands, before running anything) · `agent_notes/module_map.md` (how to generate/view/search the code index, before any grep/find)

**Read-on-demand:** `agent_notes/done_gate.md` (T0–T3 ladder, run_checks row semantics — task complete) · `agent_notes/testing.md` (markers, fixtures, test layout — before writing a test) · `agent_notes/git.md` (commit format, never-commit list — before committing) · `agent_notes/subagents.md` (delegate-when, brief format — before delegating) · `agent_notes/goal.md` (one-paragraph pitch, accept modes) · `agent_notes/description.md` (full product description, MVP acceptance criteria, out-of-scope — scoping a feature) · `agent_notes/stack.md` (stack + rationale, before adding a dependency) · `agent_notes/structure.md` (module list + tree, finding where a file belongs) · `agent_notes/insights.md` (cross-session gotchas worth carrying forward) · `agent_notes/log.md` (append-only history of bundle/convention changes)

**Scripts:** `agent_notes/utility_scripts/generate_module_map.py` / `view_module_map.py` / `search_module_map.py` (see `module_map.md`) · `agent_notes/utility_scripts/run_checks.sh` (Done Gate: lint + format + docstyle + tests; scoped/short pytest runs) · `agent_notes/utility_scripts/cleanup.sh` (end-of-session format + module-map regen) · `agent_notes/utility_scripts/validate_okf.py` (run after adding/renaming a bundle file)

**Code search order.** Locating classes, methods, functions; exploring subsystem structure; finding call sites; reading signatures; understanding file organization → invoke `Skill("codebase-navigation")` (wraps the module-map scripts) or read `agent_notes/module_map.md` directly, run the scripts it documents FIRST. grep/semantic search only after the map comes up short. Map stale/missing → `python agent_notes/utility_scripts/generate_module_map.py`, or fall back to grep and flag it in the report.

New durable fact (gotcha, why-this-design, API quirk, invalidated assumption) discovered mid-task → add it to the relevant file in this bundle before ending the session; cross-session observations go in `insights.md`, one dated line for a nontrivial bundle/convention change goes in `log.md`; update `agent_notes/index.md` if it's a new file. Skip if nothing durable was learned — say "no notes update needed", don't pad.

Note contradicts code → code wins, fix note in the same commit.
