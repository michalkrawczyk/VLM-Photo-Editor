# Instruction: generate or adapt CLAUDE.md

Current repo: !`pwd`
Existing CLAUDE.md: @CLAUDE.md
Existing agent notes: @.agent_notes

## Procedure

1. INVENTORY this repo: stack, package manager, layout, real build/test/lint commands
   (`pyproject.toml` / `Makefile` / CI config). State what you found.
2. INVENTORY `.agent_notes/` — every `*.md`, every script. See the inventory rule below.
3. If the CLAUDE.md injected above is non-empty → ADAPTING: read `.agent_notes/insights.md`, skim
   `decisions/*.md` and `gotchas/*.md` headlines. Empty or absent → CREATING: skip to 4.
4. VERIFY every tool, marker, path and version the templates below name, against step 1. Unverified →
   drop that line from the template. Never carry a template token you did not confirm in this repo.
5. DECIDE placement per section using the inline-vs-offload test below.
6. DRAFT CLAUDE.md, plus every `.agent_notes/` concept file a stub points at. No stub without its file.
7. VALIDATE: `python3 .agent_notes/tools/validate_okf.py .agent_notes` if the script exists.
8. OUTPUT per the contract at the end of this file. Propose only — write nothing unless `--apply` was
   passed and confirmed.

## Generator rules

No fabrication — verify every command, path, marker, version in-repo. Unverifiable → `TODO: confirm`.

Commands go to `.agent_notes/commands.md`, derived from `pyproject.toml` / `Makefile` / CI config. Not into CLAUDE.md.

Prefer single atomic commands over shell chains (`&&`, `||`, `;`, `|`) — atomic commands can be allowlisted individually in `.claude/settings.json` (e.g. `Bash(pytest:*)`); chains can't be scoped as precisely. Chain only when genuinely necessary. Any necessary chain → its own entry in the "Chains" section of `.agent_notes/commands.md` (command + one-line why), not inlined raw.

**Inventory `.agent_notes/` first.** List every `*.md` and every script (`tools/`, `*.py`, `*.sh`). For each, read enough to write one CLAUDE.md line: `path — what it holds — when to read/run it`. Group as: read-at-start · read-on-demand · scripts. Unclear purpose → open it; still unclear → `TODO: describe`. Never list a file without a trigger condition. Never invent files not on disk.

`tools/run_checks.sh` present → edit it for this repo, don't just copy it: set `PKG` to the real package/module and confirm that path exists (pydocstyle target — the template's `vlm_photo_editor` default is a placeholder; left unchanged it silently WARNs against a nonexistent package, since pydocstyle runs advisory-only). Verify the lint/format toolchain it assumes (ruff, black, isort, pydocstyle) against what this repo actually runs (`pyproject.toml` / CI config) and adjust or drop steps that don't apply. Pytest path scope self-detects (`tests/` → `test/` → pytest's own discovery) — no edit needed there. Note any toolchain substitution in `commands.md`.

`module_map.md` exists → read it, copy the real generate/view/search invocations into the CLAUDE.md search-order rule verbatim. Absent → write the rule with `TODO: confirm` and don't guess script paths.

**Placement — decide inline vs offloaded, per section.** CLAUDE.md loads every turn; `.agent_notes/` loads only when opened. Cost of inlining is tokens on every turn. Cost of offloading is a rule that never fires.

Test per section:
- Must fire unprompted, with no cue the agent can detect → **inline, always**
- Fires at a hard, observable trigger the agent cannot miss (about to commit / write a test / delegate / call the task done) → **offload, leave a stub**
- Contains a prohibition or a number ("never `--no-verify`", "≤50 chars", "T3 needs human confirm") → **that line stays inline** even if the rest offloads

Stub format in CLAUDE.md — trigger + prohibitions + link, 2–4 lines:
```
## Git Commits
Before any commit: read `.agent_notes/git.md`. Conventional Commits, subject ≤50.
Never commit secrets, generated files, binaries. No AI attribution or emoji.
```

Defaults (override per project):

| Section | Placement | Why |
|---|---|---|
| Mission, Precedence | Inline | No trigger; frames everything |
| Communication Style + Behavioral Guidelines | Inline, verbatim | Applies to every token emitted |
| Challenge | Inline | Fires on plans the agent doesn't recognize as plans |
| Stuck | Inline | Fires exactly when the agent is least likely to go read a file |
| `.agent_notes/` protocol | Inline | Bootstraps every other lookup |
| Done Gate | Stub → `.agent_notes/done_gate.md` | Trigger is unmissable (task complete); tier ladder is long. Keep inline: tier names, "no green claim without command output", T3 human confirm |
| Testing | Stub → `.agent_notes/testing.md` | Trigger: about to write a test. Keep inline: extend > create, parametrize not loops |
| Git Commits | Stub → `.agent_notes/git.md` | Trigger: about to commit. Keep inline: format, ≤50, never-commit list |
| Subagents | Stub → `.agent_notes/subagents.md` | Trigger: about to delegate. Keep inline: don't-delegate list, "rerun the gate yourself" |
| Commands | Offload fully → `commands.md` (Atomic + Chains sections) | Never needed from memory |

Offloading anything means the target file must exist and be listed in the inventory. Never leave a dangling reference — a stub pointing at a missing file is worse than inlining.

Adapting existing CLAUDE.md: first read `.agent_notes/insights.md` if present (skim `decisions/*.md` and `gotchas/*.md` headlines too) — fold any durable, non-project-specific lesson into the relevant CLAUDE.md section instead of leaving it stranded. Then keep project-specific facts, replace only generic overlaps, move unknowns to `.agent_notes/`. Create missing OKF concepts as stubs.

Budget ≤300 lines inline (stubs, not full sections) — file loads every turn. §2 is verbatim and non-negotiable; trim elsewhere.
Section order:
Mission → Precedence → Challenge → Done Gate → Stuck → Communication Style + Behavioral Guidelines → Subagents → Testing → Git → `.agent_notes`.

Precedence is emitted as its own `## Precedence` heading in CLAUDE.md, one line, verbatim:

```markdown
## Precedence
Session instruction > CLAUDE.md > `.agent_notes/` > defaults.
```

---

## 1. Project Mission

Short, precise: what the project does, who uses it, **non-goals**, maturity stage. Non-goals are what stop speculative work.

---

## 2. Communication Style + Behavioral Guidelines (verbatim)

Insert exactly as given. Do not compress, reword, or relocate. Everything between the four-backtick
fences is CLAUDE.md content — the three-backtick block inside it is part of that content.

````markdown
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
````

Optional addition to the block's own `## 3. Surgical Changes` subsection (not this file's §3), only if the
project uses an autoformatter: `Formatter output wins over local style.`

---

## 3. Challenge

```markdown
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

High-stakes plan (T2/T3, irreversible, or multi-step with real cost if wrong) → run this Challenge via a
fresh subagent instead of self-critiquing (see Subagents). You're anchored to your own plan; it isn't.
Cheap plans stay in-thread.
```

---

## 4. Done Gate

Full text → `.agent_notes/done_gate.md`. CLAUDE.md gets only the stub after this block.

`mypy src` below is a placeholder: verify mypy is actually configured (`pyproject.toml` / CI) and verify the
real source path. Not configured → delete the line, don't weaken it to `TODO: confirm`. Same for any other
tool you add here.

````markdown
## Done Gate

T0 docs only: saved.

T1 any code:
  1. `.agent_notes/tools/run_checks.sh --check` exit 0 AND summary shows no `SKIP` for a tool this repo
     uses — SKIP means the tool isn't installed, which is not a pass
  2. `mypy src` no new errors
  3. Every changed line traces to request

T2 behavior change: T1 +
  4. Test fails on old code, passes on new — state how verified
  5. No leftover TODO/commented code

T3 schema, migration, public API, dep, config: T2 +
  6. `.agent_notes/tools/run_checks.sh --check --full` exit 0 (full suite)
  7. Rollback path, one line
  8. Human confirm before commit

Report: `Changed: … | Ran: cmd → result | Assumptions: … | Not done: …`
No green claim without command output. Unverified → say "unverified".
Pre-existing failure blocks gate → report it, proceed only if unrelated to diff.
run_checks.sh covers lint/format/docstyle/pytest; tools outside it (e.g. mypy) stay separate lines here.
pydocstyle is advisory in that script and never fails the run — a WARN is not a green docstring check.
````

CLAUDE.md stub:

```markdown
## Done Gate
Before calling any task done: read `.agent_notes/done_gate.md`. Tiers: T0 docs · T1 code · T2 behavior · T3 schema/migration/public API/dep/config.
No green claim without command output. `SKIP` in the checks summary is not a pass. Unverified → say "unverified".
T3 requires human confirm before commit.
```

---

## 5. Stuck

```markdown
## Stuck

Same error 3x → stop. Report diagnosis, attempts, what's needed.
Never: skip/xfail, `# type: ignore`, `except: pass`, mock the failure, weaken assertion, delete test, `--no-verify`.
```

---

## 6. Subagents

Full text → `.agent_notes/subagents.md`. CLAUDE.md gets only the stub after this block.

````markdown
## Subagents

Delegate to keep main context clean and cheap. Subagent burns its own context, returns only its report.

**Delegate when:**
- Search/exploration will read many files to yield a small answer (locate implementation, map call sites, find which of 20 files matches)
- Reading bulk artifacts: logs, dumps, generated output, long docs, third-party source
- Independent verification: fresh eyes on a diff, reproducing a bug, checking a claim without inheriting your assumptions
- Two or more independent branches of work with no shared state
- Main context is filling and remaining work needs room
- Multi-step plan: for each step, weigh whether delegating it to a subagent reduces main
  context without losing context the step actually needs — delegate the steps that clear that bar
- High-stakes plan about to execute (T2/T3, irreversible, or costly if wrong) → delegate its Challenge
  review: a fresh subagent isn't anchored to your assumptions. Unlike the cases above, this doesn't
  save context — it needs the whole plan — the payoff is an unanchored critique, not cheapness

**Don't delegate:**
- Anything requiring the conversation's accumulated context — it doesn't transfer
- Small/known-path lookups: cheaper to read directly than to brief an agent
- Write decisions, architecture choices, API design, tradeoff calls
- The Done Gate — parent runs it, on its own machine, and owns the result
- Commits

**Brief format** (subagent has zero context — omit nothing):
```
Goal: [one sentence, verifiable]
Scope: [paths in/out of bounds]
Method: module_map scripts first, then grep. Read-only unless stated.
Return: [exact shape — file:line list, table, yes/no + evidence]
Budget: [max files/steps]
```

**Handling results:**
- Report is a claim, not a fact. Verify anything you act on — open the cited file:line.
- Unverifiable or vague return → rerun with a tighter Return spec, don't guess.
- Never let a subagent's "tests pass" satisfy T1–T3. Rerun yourself.
- Parallel agents → check for contradictions before merging. Contradiction = investigate, not average.

Report delegation in your summary: `Delegated: [what] → [what came back].`
````

CLAUDE.md stub:

```markdown
## Subagents
Before delegating: read `.agent_notes/subagents.md`. Brief format is mandatory — subagent has zero context.
Never delegate: the Done Gate, commits, write/architecture decisions, anything needing this conversation's context.
Subagent report is a claim, not a fact — verify what you act on. Rerun the gate yourself.
```

---

## 7. Testing

Full text → `.agent_notes/testing.md`. CLAUDE.md gets only the stub after this block.

Placeholders to verify before emitting: the marker line (`slow`, `integration`) must match this repo's real
`markers =` in `pyproject.toml`/`pytest.ini` — different names → use theirs, none defined → delete the line.
`playwright` — drop unless the repo actually depends on it. `.tmp_scripts/` stays regardless.

````markdown
## Testing

Grep existing coverage before new test file — extend > create. Check if tested methods fit existing pipelines.
Markers: `slow` (long-running), `integration` (requires full pipeline). Default run excludes `slow`.

Fewer test functions, broader coverage. `@pytest.mark.parametrize` — never `for` loops.
Merge related assertions (schema + round-trip + error case) into one test.
Assert behavior, not call counts, unless the call IS the contract.

Prefer pytest and playwright over `python -c` and shell scripts. Session-written scripts → `.tmp_scripts/`.
````

CLAUDE.md stub:

```markdown
## Testing
Before writing a test: read `.agent_notes/testing.md`. Grep existing coverage first — extend > create.
`@pytest.mark.parametrize`, never `for` loops. Session-written scripts → `.tmp_scripts/`, never `python -c`.
```

---

## 8. Git Commits

Full text → `.agent_notes/git.md`. CLAUDE.md gets only the stub after this block.

````markdown
## Git Commits

Conventional Commits. Subject ≤50 chars (hard cap 72). Imperative mood. No trailing period.
Format: `<type>(<scope>): <summary>`. Types: feat, fix, refactor, perf, docs, test, chore, build, ci, style, revert.
Body only for non-obvious why, breaking changes, migration notes, `Closes #N`.
No AI attribution or emoji.
````

CLAUDE.md stub:

```markdown
## Git Commits
Before any commit: read `.agent_notes/git.md`. Conventional Commits, subject ≤50 chars, imperative mood.
Never commit secrets, generated files, binaries. Never `--no-verify`. No AI attribution or emoji.
```

---

## 9. .agent_notes/

Emit the **Code search order** paragraph only if `module_map.md` and its scripts exist on disk (same
condition as the `module_map.md` rule above) — otherwise a rule that can never fire sends every search to a
missing file. Emit the regeneration sentence only if a post-session hook is actually configured in
`.claude/settings.json`; no hook → delete it.

````markdown
## .agent_notes/

OKF v0.1 bundle. One concept per file, path = identity, cross-link with markdown links.
Frontmatter: `type` required; add title, description, tags, timestamp (ISO-8601 UTC); resource if external.

Read `index.md` at task start; open only what the task touches.
Write back durable non-obvious facts (gotcha, why-this-design, API quirk). Status → `log.md`.
Observation, key decision, or conclusion surfaced during any agent/subagent session that could
improve future runs → write it to `insights.md`, not just the session report.
New concept → link + one line in `index.md`.
Note contradicts code → code wins, fix note same commit.

**Task end — update bundle when warranted.** Task complete = session end. Before final report/commit,
sweep for: new decision + its reason, gotcha hit, invalidated assumption, discovered constraint,
command that turned out wrong, design conclusion, idea deferred rather than dropped. Each → new
concept or edit to existing one; refresh `timestamp`; update `index.md`; append one dated line to `log.md`.
Skip when nothing durable was learned — say "no notes update needed", don't pad.
Not for: task status, restating the diff, anything readable from code.

After writing any concept: run `.agent_notes/tools/validate_okf.py <path>` if present.
Non-zero exit → fix before commit. Script absent → skip, don't create.

**Code search order.** Locating classes, methods, functions; exploring subsystem structure; finding
call sites; reading signatures; understanding file organization → read `module_map.md`, run the map
scripts it documents FIRST. grep/semantic search only after the map comes up short.
Map stale or missing → note it, fall back to grep/semantic search, flag in report.
Regeneration runs in a post-session hook — don't regenerate mid-task unless asked.

**Documentation is OKF too.** Project docs live in the bundle (or their own OKF directory), same rules:
one concept per file, `type` required, cross-linked, `index.md` for entry, `timestamp` refreshed on edit.
No parallel doc system. Doc request → OKF concept, not an ad-hoc README.

<generated inventory goes here — one line per file, with trigger condition>
````

Default concept set (create as stubs if missing):

| File | `type` | Holds | Read when |
|---|---|---|---|
| `index.md` | Index | Map of bundle | Task start |
| `commands.md` | Runbook | Two sections: Atomic (verified build/test/lint/run commands, allowlist-able individually) and Chains (necessary shell chains — `&&`/`\|`/`;`/`\|\|` — that couldn't be split, one entry + one-line why each) | Before running anything (Atomic) / before running a multi-step or piped command (Chains) |
| `module_map.md` | Runbook | How to generate, view, and search the module map — usage of the map scripts in `.agent_notes/` | Locating classes/methods/functions, exploring subsystem structure, finding call sites, reading signatures, understanding file organization — before any search |
| `conventions.md` | Playbook | Project style, naming, error/logging patterns, plus a `## Glossary` section mapping domain terms → code symbols | Before writing new code, or when a request uses domain language |
| `testing.md` | Playbook | Fixture map, marker semantics, pipelines to extend, plus §7's full text | Before adding tests |
| `done_gate.md` | Runbook | §4's full tier ladder T0–T3 and the report format | Before calling any task done |
| `git.md` | Playbook | §8's full commit rules, types, body policy, never-commit list | Before any commit |
| `subagents.md` | Playbook | §6's full delegate/don't-delegate lists, brief format, result handling | Before delegating |
| `gotchas/*.md` | Gotcha | One trap per file | On matching error |
| `decisions/*.md` | Decision | Context, choice, consequence | Before contradicting existing design |
| `log.md` | Log | Chronological, append-only | Rarely; write on nontrivial change |
| `insights.md` | Insight | Observations, decisions, conclusions from agent/subagent sessions that could improve future runs | Session end; before improving main-agent guidance |
| `tools/validate_okf.py` | — | Frontmatter/link validator | After writing any concept |
| map scripts | — | Generate / view / search module map — paths and invocation documented in `module_map.md` | Before grep/semantic search |

`.tmp_scripts/`: gitignored, never imported by the package. Delete at task end. Ran twice → make it a pytest.

OKF spec: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf

---

## Output contract

Report in this order:

1. Table: `path | new/modified/deleted | reason` — every file you propose to create or change.
2. Full content of each file, in code blocks.
3. Unresolved list: every `TODO: confirm` left in the drafts, and every template line you dropped as
   unverifiable, one line each.

Write behavior: **propose only by default — write nothing.** With `--apply`, ask for explicit y/n before
writing. An existing CLAUDE.md is never overwritten without showing a diff against it first.