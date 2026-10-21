# Harness Review — Issues & Improvements

**Date:** 2026-10-19 · **Branch:** `develop` · **Scope:** the *agent harness* — `CLAUDE.md`, `agent_notes/`, `.claude/` (settings, hook, skills, commands), `run_checks.sh` / `cleanup.sh` Done Gate, module-map tooling, review-loop workflow.
**Out of scope:** product/code defects (tracked in [plans/issues.md](plans/issues.md)).
**Method:** read-only. Every number below was re-derived on 2026-10-19 with the commands in [Re-verify](#re-verify). `.env` contents were deliberately not read.

---

## Summary

| ID | Severity | Area | Issue | Fix effort |
|---|---|---|---|---|
| H-1 | **Critical** | Gate | Fast gate has 11 failing tests not in the documented baseline (AppTest path + unpinned deps) | S |
| H-2 | **High** | Safety | Permission allowlist: no `deny`, `git commit *` auto-allowed, arbitrary-exec wildcards, 25 dead entries | S |
| H-3 | **High** | Portability | `.claude/` and `CLAUDE.md` are gitignored — harness not versioned | S |
| H-4 | **High** | Gate | No CI, no git hooks; gate is honor-system and permanently red on ruff | M |
| H-5 | **High** | Enforcement | Import boundaries documented in AGENTS.md, unenforced, already violated | M |
| H-6 | Medium | Safety | Stop hook runs formatters on every turn; silent failure; wrong PATH | S |
| H-7 | Medium | Gate | `run_checks.sh` defaults to fix mode; no `--changed` lint | S |
| H-8 | Medium | Docs | Quoted counts drifted (ruff, AGENTS.md coverage, test layout) | S |
| H-9 | Medium | Workflow | `plans/issues.md` is 156 KB — exceeds Read cap; loop state untracked | M |
| H-10 | Medium | Gate | `[tool.mypy]` config is dead; skill still claims "type check" | S |
| H-11 | Medium | Skills | `pre-commit` skill short-circuits on red ruff, cites nonexistent paths, duplicates gate | S |
| H-12 | Medium | Commands | Stale/non-portable commands; nav skill names tools this harness lacks | S |
| H-13 | Low | Tooling | Module map has no freshness guard | S |
| H-14 | Low | Docs | CLAUDE.md duplicates bundle content; instruction conflicts unstated | M |
| H-15 | Low | Docs | `insights.md` mixes product facts with harness lessons; 6 modules lack AGENTS.md | M |
| H-16 | Low | Gate | `--full` is not a release gate (excludes e2e + VLM eval) | S |

Effort: S ≤ 1 h · M ≤ 1 day.

### Strengths (keep these)

- `run_checks.sh`: `SKIP` ≠ `PASS`, real exit code recovered via `PIPESTATUS`, runs every step, summary table is the evidence.
- `validate_okf.py` passes 4/4 (links, index, orphans, pointers).
- Honest-baseline culture: `done_gate.md` and `insights.md` admit the gate is red instead of hiding it.
- Fast gate is cheap: `pytest -m "not slow"` = 22 s.
- "Code wins over notes" precedence rule; module-map-first search order.

---

## A. Gate integrity

### H-1 — Fast gate is red beyond the documented baseline *(Critical)*

**Evidence:** `pytest -m "not slow" -q` → `11 failed, 779 passed, 1 skipped, 17 deselected`. All 11 in [tests/unit/test_p13_character_focus.py](tests/unit/test_p13_character_focus.py):

```
FileNotFoundError: AppTest script not found at
.../tests/unit/vlm_photo_editor/app/main.py. Relative paths are resolved against the
file that calls AppTest.from_file().
```

Installed Streamlit is 1.65.0 and resolves relative `AppTest.from_file` paths against the *calling file*. Tests pass a repo-relative path. [requirements.txt:34](requirements.txt#L34) is `streamlit>=1.36`; there is no lockfile; dev tools float too (`black 26.10.1`, `ruff 0.17.0`, `isort 9.0.2`, `pytest 9.1.1`).
[CLAUDE.md:67](CLAUDE.md#L67) and [done_gate.md](agent_notes/done_gate.md) state that only `ruff` is red.

**Impact:** an agent (or human) sees red tests, follows the doc, assumes "pre-existing, not mine", and a real regression hides among them. This is the failure mode `insights.md` already warned about for ruff.

**Fix:**
1. Make tests path-independent: `Path(__file__).resolve().parents[2] / "vlm_photo_editor/app/main.py"` (works on old and new Streamlit).
2. Pin or constrain: add upper bounds or a constraints/lock file (`pip freeze > requirements.lock`, or `uv lock`).
3. Add a "Known red" row for tests to `done_gate.md` until (1) lands, then delete it.

**Weak point / alternative:** root cause inferred from Streamlit 1.65 semantics, not bisected on older versions. Step 1 is version-independent, so the fix does not depend on the guess.

### H-4 — Gate is honor-system, permanently red on ruff *(High)*

**Evidence:** no `.github/`, no `.pre-commit-config.yaml`, `.git/hooks` has only samples, `core.hooksPath` unset; [commands.md](agent_notes/commands.md) states "No Makefile, no CI config exists". `ruff check .` → 40 errors on a clean tree, so "every BLOCK row PASS" ([CLAUDE.md](CLAUDE.md) T1) is unreachable.

**Impact:** nothing stops a red commit; a permanently red row trains everyone to ignore the table (alarm fatigue — a known failure of always-lit annunciators; the ISA-18.2 rule is "every alarm actionable, baseline zero").

**Fix:**
1. Zero the baseline: 40 errors / 9 files. E501 (22) is prompt strings in `templates/`, `schema/op_catalog.py`; E402 (14) is deliberate lazy imports in `app/` → `[tool.ruff.lint.per-file-ignores]` in [pyproject.toml](pyproject.toml) for those paths; fix F841 (1), F821 (2, false positives already carrying `# type: ignore`), I001 (1, auto-fixable) directly.
2. Then enforce: `.git/hooks/pre-push` (or a tracked `scripts/hooks` + `core.hooksPath`) running `run_checks.sh --check --short`.
3. Only if the repo gains collaborators: CI.

**Weak point / alternative:** CI for a solo local project is over-built; a pre-push hook gets 90 % of the value at ~5 lines.

### H-7 — `run_checks.sh` defaults to fix mode *(Medium)*

**Evidence:** [run_checks.sh:117](agent_notes/utility_scripts/run_checks.sh#L117) — without `--check` it runs `ruff check --fix .`, `black .`, `isort .` repo-wide. The Done Gate (T1) invokes it with no flag.

**Impact:** the "gate" edits files, including ones outside the diff — conflicts with CLAUDE.md "every changed line traces to request". The interim pass rule ("no new ruff errors in files your diff touched") has no tooling and is checked by hand.

**Fix:** invert the default (`--check`), add `--fix` for opt-in mutation, add `--changed` (lint only `git diff --name-only` + untracked `.py`). Update `done_gate.md` and `commands.md` in the same commit.

### H-10 — mypy config is dead *(Medium)*

**Evidence:** `[tool.mypy] strict = true` in `pyproject.toml`; mypy absent from [requirements_dev.txt](requirements_dev.txt) and `.venv`; no script runs it. The `pre-commit` skill description says "format, type check, tests".

**Impact:** the strict config reads as evidence of type safety that was never measured.

**Fix:** either (a) add mypy to dev deps and a non-blocking `WARN` row to `run_checks.sh`, or (b) delete `[tool.mypy]` and fix the skill text. (a) is preferable only if someone will burn down the error count; otherwise (b).

### H-16 — `--full` is not a release gate *(Low)*

**Evidence:** [done_gate.md](agent_notes/done_gate.md): `--full` only drops `not slow`; `addopts = ["-m","not e2e"]` still applies; VLM-eval needs `EVAL_VLM=1`. T3 says "`--full` green".

**Impact:** T3 changes (schema/API/config) reach commit without ever touching the e2e flow that exercises them.

**Fix:** document one explicit pre-release recipe (`pytest -m "e2e or slow"` with cost note) and reference it from T3 as optional-with-reason.

---

## B. Permissions & safety

### H-2 — Permission allowlist is unsafe and rotted *(High)*

**Evidence:** [.claude/settings.json](.claude/settings.json) has 83 allow entries, `.claude/settings.local.json` 22; **no `deny` block**.

| Problem | Examples |
|---|---|
| Commits auto-approved — removes the prompt that enforces T3 "human confirm before commit" | `Bash(git commit *)`, `Bash(git commit -m *)`, `Bash(git add *)`, `Bash(git reset *)`, `Bash(git apply *)` |
| Arbitrary execution | `Bash(python *)`, `Bash(python3 *)`, `Bash(pip install *)`, `Bash(python -)`, `Bash(python3 -)`, `Bash(python3)` |
| Meaningless | `Bash(auto)` |
| Dead session-scratch paths (25 entries; two use a non-existent project slug `-media-tk-Programming-Python-…`) | `python3 /tmp/claude-1000/…/extract_hunks.py …` |
| Duplicates | `Bash(ruff check *)` twice in one file; 3 entries repeated across both files |
| No guard for secrets despite Principle 2 ("non-negotiable") | no `Read(.env*)` / `Bash(cat .env*)` deny |

**Impact:** `python *` makes every narrower `python -m pytest …` entry decorative; allowed commit + `pip install` + `python` means the permission layer constrains almost nothing. A prompt-injected instruction in a file the agent reads (see `plans/issues.md` PLN-D1/AGT-D3 for the same class of risk in the product) could run code with no prompt.

**Fix:** rewrite to ≈15 entries: `Bash(python -m pytest *)`, `Bash(.venv/bin/pytest *)`, `Bash(ruff check *)`, `Bash(ruff format *)`, `Bash(bash agent_notes/utility_scripts/run_checks.sh*)`, module-map scripts, read-only `git status|diff|log|show`. Add `deny`: `Read(./.env)`, `Read(./.env.*)` (allow `.env.example`), `Bash(git push *)`, `Bash(git commit --no-verify*)`. Leave `git commit` to prompt.

**Weak point / alternative:** the user clearly accepted frequent commits (split-commits workflow). Alternative that keeps flow: allow `git commit` but add a `PreToolUse` hook that blocks it when the diff touches T3 paths (`pyproject.toml`, `schema/`, `requirements*.txt`).

### H-6 — Stop hook mutates the tree every turn *(Medium)*

**Evidence:** [settings.json:92-103](.claude/settings.json#L92) runs `agent_notes/utility_scripts/cleanup.sh || true` on **every** `Stop` (end of every assistant turn, including plan-mode and read-only turns). [cleanup.sh](agent_notes/utility_scripts/cleanup.sh) is labelled "End-of-session", runs `black` + `isort` on `vlm_photo_editor/ tests/`, then regenerates the map. Unlike `run_checks.sh` it never prepends `.venv/bin` to `PATH`; it has no `set -e`/tool checks; the hook adds `|| true`.

**Impact:** (1) files change under the user's editor mid-session; (2) formatter scope (`vlm_photo_editor/ tests/`) differs from the gate (`black .`) — two definitions of "formatted"; (3) if the hook environment lacks `black`, every turn silently skips formatting (failure is swallowed twice). Behavior in the hook environment was **not** observed — see [Confidence](#confidence--open-questions).

**Fix:** split: hook runs only map regeneration (idempotent, gitignored output); formatting moves to `run_checks.sh --fix`. If formatting stays in the hook, restrict to files in `git diff --name-only`, prepend `.venv/bin`, and print `SKIP` instead of failing silently.

---

## C. Versioning & portability

### H-3 — Harness is not versioned *(High — flagged as risk; choice is deliberate)*

**Evidence:** `.gitignore` ends with `.claude/` ("kept on disk, not versioned") and `CLAUDE.md`; commits `47a96ac`, `54bfc66`, and `agent_notes/log.md` (2026-10-16) record this as intentional. The session banner still says CLAUDE.md is "checked into the codebase". `agent_notes/*` links to CLAUDE.md; [validate_okf.py:248-256](agent_notes/utility_scripts/validate_okf.py#L248) returns exit 2 ("not a file") when it is absent. `git ls-files` shows no `.claude/` or CLAUDE.md.

**Impact:** a fresh clone, a disk failure, or a second machine has the notes bundle but none of: the hook, the skills, the 10 commands, the permissions, or the project rules. The tracked `agent_notes/` cites rules it can't show.

**Fix (objection stated once; user's choice stands):** track `.claude/settings.json`, `.claude/skills/`, `.claude/commands/`, and `CLAUDE.md`; ignore only `.claude/settings.local.json`. If privacy is the reason (hard-coded `/home/tk/…` paths, scratch paths), clean those first (H-2, H-12) — then nothing sensitive remains.

**Alternative:** keep untracked but add a tracked `agent_notes/harness_snapshot/` refreshed by `cleanup.sh`, or make `validate_okf.py` treat a missing CLAUDE.md as `SKIP`.

### H-12 — Commands and skills are stale or non-portable *(Medium)*

| File | Problem |
|---|---|
| [.claude/commands/identify-goal.md:2](.claude/commands/identify-goal.md#L2) | Writes `.agent_notes/goal.md` — CLAUDE.md says the dir is `agent_notes/`, "not `.agent_notes/`" |
| [.claude/commands/claude-builder.md](.claude/commands/claude-builder.md) (449 lines) | Emits the `.agent_notes/tools/run_checks.sh` layout this repo explicitly rejected; running it would regenerate the old structure |
| [.claude/commands/test_review_loop.md](.claude/commands/test_review_loop.md) | Hard-codes `/home/tk/.claude/plugins/marketplaces/…/setup-ralph-loop.sh` |
| `review_loop.md` | Depends on the `ralph-loop` plugin (`enabledPlugins`) and on `batch_review` resolving as a *Skill* although it is a command |
| [.claude/skills/codebase-navigation/SKILL.md:8](.claude/skills/codebase-navigation/SKILL.md#L8) | "BLOCKING RULE … before any `grep_search` or `semantic_search`" — those tool names don't exist in this harness (Grep/Glob); rule is ambiguous at the exact moment it matters |
| `verify-decisions.md` | One sentence, no output contract |

**Fix:** correct the paths, rename the nav-skill terms to `Grep`/`Glob`, delete or archive `claude-builder.md` and `test_review_loop.md` if unused, give `verify-decisions` a template.

---

## D. Enforcement gaps

### H-5 — Import boundaries are documented, unenforced, already violated *(High)*

**Evidence (verified by grep 2026-10-19):**

| Edge | Site | Rule broken |
|---|---|---|
| `planner → background` | [planner/compiler.py:6-13](vlm_photo_editor/planner/compiler.py#L6) | `planner/AGENTS.md`: must NOT import `background` |
| `agents → ops` | [agents/planner.py:96,139,190](vlm_photo_editor/agents/planner.py#L96) (`frame_target_size`), [agents/edit_flow.py:73,97](vlm_photo_editor/agents/edit_flow.py#L73) | `agents/AGENTS.md`: must NOT import `ops` |
| `planner → ops` | [planner/compiler.py:13](vlm_photo_editor/planner/compiler.py#L13), [planner/repair.py:87](vlm_photo_editor/planner/repair.py#L87) | CLAUDE.md "planner never imports `ops/`" — but `planner/AGENTS.md` *allows* `ops.validator` (two contract docs disagree) |
| `schema → siblings` | none found | **Holds** |

Only boundary-ish test in `tests/` is unrelated (mask feathering). The violations are also logged as PL-P2/PL-P3 in `plans/issues.md` — i.e. detected by manual review, not by the harness.

**Impact:** CLAUDE.md calls these "strict boundaries"; Principle 7 says contracts first. Rules that no tool checks decay silently — 3 of 10 AGENTS.md-bearing layers already breach theirs.

**Fix:**
1. One parametrized AST test `tests/unit/test_import_boundaries.py` encoding each AGENTS.md "Must NOT import" list (function-local imports included via `ast.walk`). Start with an explicit allowlist of the 5 known violations so it lands green, then shrink the list.
2. Reconcile CLAUDE.md ↔ `planner/AGENTS.md` on `ops.validator` — pick one.

**Alternative:** `import-linter` (declarative contracts) — more standard, but adds a dependency (T3) for ~10 rules a 40-line test covers.

### H-13 — Module map has no freshness guard *(Low)*

**Evidence:** [module_map.md](agent_notes/module_map.md): "Not automatic mid-task"; only the Stop hook regenerates. The nav skill's rule is BLOCKING — use the map first.

**Impact:** after edits, `search_module_map.py` returns stale line numbers/signatures with no warning; the agent follows them confidently.

**Fix:** in `search_module_map.py` / `view_module_map.py`, compare `module_map.json` mtime with the newest `*.py` under the scanned dirs and print `WARNING: map older than source — regenerate` to stderr.

---

## E. Documentation hygiene

### H-8 — Quoted counts drifted *(Medium)*

`agent_notes/insights.md` already records "duplicating a fact inline is what caused the drift". It recurred:

| Claim (where) | Actual (2026-10-19) |
|---|---|
| 48 ruff errors / 12 files, E501 23, E402 20, F841 2 ([CLAUDE.md:67](CLAUDE.md#L67), [done_gate.md](agent_notes/done_gate.md), [insights.md](agent_notes/insights.md)) | **40 / 9 files**, E501 22, E402 14, F841 1, F821 2, I001 1 (likely tool-version drift too — H-1) |
| AGENTS.md "9/15 modules" ([CLAUDE.md:200](CLAUDE.md#L200)) | 10 of 16 (`structure.md` lists the 10 correctly; missing: config, models, pipeline, preferences, recipe, templates) |
| `tests/integration/` "currently empty" ([testing.md](agent_notes/testing.md)) | 2 test files (`test_batch_modes.py`, `test_p8_5_mvp_gate.py`) — `insights.md` cites the latter |
| `tests/unit/` "15 files" ([testing.md](agent_notes/testing.md)) | 17 `test_*.py` files |
| "122 passed, 2 skipped" ([plans/issues.md](plans/issues.md) header) | 808 collected (795 w/o e2e) |

**Fix:** delete counts that can be computed; where a count adds value, replace with the command that produces it. Extend `validate_okf.py` with a check that any `N/M` or "N errors" figure in CLAUDE.md/done_gate has a matching `<!-- verify: cmd -->` and is re-run.

### H-9 — `plans/issues.md` is unmanageable *(Medium)*

**Evidence:** 156,314 bytes, 1,896 lines, 26 headings, 153 table rows; a single `Read` returns ~25 k tokens (a third of the file). [batch_review](.claude/commands/batch_review.md) tells the agent to insert "immediately above `## Summary`" — at line 1746. Two review rounds share one file with prefix conventions to avoid ID collision. Header "Audit date: 2026-06-16" is four months old. `plans/plan_review.md` — the loop's `[DONE]` state — is **untracked** (`?? plans/plan_review.md`), so loop progress is lost on `git clean`.

**Impact:** each batch review re-pays a large context cost to find an insertion point; closed items are pruned by hand (commit `fc494de`).

**Fix:** split by status/round: `plans/issues/open.md` (index table only) + `plans/issues/batch-NN.md` bodies; `batch_review` appends a file and a row. Track `plan_review.md`.

### H-11 — `pre-commit` skill is broken and duplicative *(Medium)*

**Evidence:** [.claude/skills/pre-commit/SKILL.md](.claude/skills/pre-commit/SKILL.md): `run_checks.sh --full && cleanup.sh`.
- `ruff` is red → script exits 1 → `&&` skips `cleanup.sh`.
- Says "type check" — none runs (H-10).
- "extract `#@agent` markers to `agent_notes/patterns/`" — directory does not exist, no markers convention elsewhere.
- Third copy of the gate (CLAUDE.md, `done_gate.md`, skill).

**Fix:** reduce to a pointer: "Run the Done Gate tier per `agent_notes/done_gate.md`." Drop the marker line.

### H-14 — CLAUDE.md duplicates bundle content; conflicts unstated *(Low)*

- 231 lines re-state `done_gate.md` (tiers, baseline numbers), `git.md` (commit format), `testing.md` (markers, `parametrize`) — each a drift source (H-8).
- Plan-mode workflow mandates Explore agents; CLAUDE.md says "don't use an Explore agent" for known paths. Both hold in their context, but the precedence line (`session > CLAUDE.md`) doesn't cover system-mode rules.
- "Terse, drop articles" style vs `/ultra-think` command's long mandatory template. Unreconciled.

**Fix:** CLAUDE.md keeps principles + pointers; mutable facts live only in `agent_notes/`. Add one line: "Slash-command templates override Communication Style for their output only."

### H-15 — `insights.md` and AGENTS.md coverage *(Low)*

- 204 lines; mixes harness lessons (good) with product facts — OpenAI reasoning-model path, `step_id` UUID normalisation, `dotenv_values` rule — that belong in `stack.md` or the owning module's AGENTS.md. No lifecycle (resolved/expired).
- The 6 modules without AGENTS.md (`config`, `models`, `pipeline`, `preferences`, `recipe`, `templates`) are where most open `plans/issues.md` items live (SEC-D1/D2/D3, RCP-*, PLN-D1, SC-C4). The `dotenv_values` and OpenAI facts above would be natural first content for `config/` and `models/`.

**Fix:** move product facts to AGENTS.md as each is written; add `Status: active|resolved` to each insight.

---

## Remediation strategy

Three genuinely different approaches:

| | Approach | Pros | Cons / failure condition |
|---|---|---|---|
| **A** | **Patch docs** — correct the stale numbers, fix paths | Minutes; fixes H-8, H-12 text | Drift recurs; `insights.md` is the proof. Fails when the next number changes |
| **B** | **Enforce by tooling** — green baseline, `--check` default, pre-push hook, AST boundary test, permission `deny`, test path fix, lock deps | Converts opinions into red/green; removes alarm fatigue; protects Principles 2/7/8 mechanically | Upfront 1–3 days; hook/CI becomes one more thing to maintain; fails if baseline isn't zeroed first (a new red check is ignored on day one) |
| **C** | **Slim the harness** — CLAUDE.md → principles + pointers, delete duplicate skill, remove dead commands | Shrinks drift surface and per-session tokens | Agents lose inline context; fails if pointers aren't followed (CLAUDE.md already depends on this) |

**Recommended: B as core, C for docs, A only for numbers that can't be removed.**

*Adversarial test (inversion — how to guarantee harness rot):* leave the baseline red, duplicate every fact in three places, auto-allow commits and arbitrary Python, never version the config, make the gate mutate the tree. The repo currently does all five (H-4, H-8/H-11/H-14, H-2, H-3, H-7). The recommendation reverses each.

*Cross-domain parallel:* aviation/process-plant alarm management — a panel that is always partly lit stops being read; the fix is a zero baseline and actionable alarms, not louder alarms. Same for a gate that is red by default.

*Second-order effects:*
- **6 months:** allowlist keeps growing by session-scratch entries; "red is normal" becomes team lore; more tests break on floating Streamlit/ruff versions.
- **2 years:** boundary violations spread beyond 3 layers; `plans/issues.md` passes 300 KB; AGENTS.md for unwritten modules never appears.
- **10 years:** unversioned `.claude/` = tribal knowledge held by one machine.

### Prioritized roadmap

1. **H-1:** absolute AppTest path + constraints file → fast gate green except ruff. *(~1 h; verify: `pytest -m "not slow"` → 0 failed.)*
2. **H-2:** prune allowlist, add `deny` for `.env`, stop auto-allowing commit. *(~30 min; verify: `jq '.permissions.allow|length'` ≈ 15.)*
3. **H-4:** ruff baseline → 0 via `per-file-ignores` + 4 direct fixes. *(~1 h; verify: `ruff check .` exit 0.)*
4. **H-7:** `--check` default, `--changed` flag. *(verify: run on a dirty file, tree unchanged.)*
5. **H-5:** boundary test with known-violation allowlist, then reconcile CLAUDE.md/planner AGENTS.md.
6. **H-3:** version harness (after steps 1–2 clean the paths).
7. **H-6, H-11, H-12, H-8, H-14:** hook split, skill/command cleanup, doc de-dup.
8. **H-9:** split `plans/issues.md`.

### Success metrics

- `bash agent_notes/utility_scripts/run_checks.sh --check` exits 0 on a clean tree.
- `git ls-files` includes `CLAUDE.md` + `.claude/settings.json` (or the chosen alternative is documented).
- `settings.json` allow ≤ 20 entries, `deny` contains `.env`.
- Zero hand-maintained counts in CLAUDE.md/done_gate.md.
- Boundary test fails when a forbidden import is added.

---

## Confidence & open questions

| Claim | Confidence | What would change it |
|---|---|---|
| H-1 failures and cause | High (reproduced; error text quoted) | Older Streamlit passing is plausible but not tested; fix doesn't depend on it |
| H-2 permission analysis | High (read file) | A user-level `~/.claude/settings.json` with `deny` rules would soften it — not inspected |
| H-6 silent skip of black | **Low** — hook environment's `PATH` not observed | Run `cleanup.sh` under the hook's env (`env -i PATH=/usr/bin:/bin`) |
| H-5 violations | High (grep) | Intentional exemption for `edit_flow` (orchestration must reach executor) would downgrade 2 of 3 edges to "doc is wrong" |
| H-3 | Medium — it is a recorded decision; severity depends on how much the user relies on a second machine/backup | A separate backup of `.claude/` |
| Severity ordering | Medium — judgement on single-machine evidence | Effort column lets you re-rank |
| `.env` safety | **Unknown** — contents not read; only that no deny rule exists | — |

**Open questions for the owner:** (1) Is `.claude/` untracked for privacy or for convenience? (2) Is `edit_flow.py` intended to be exempt from the `agents/` boundary? (3) Is CI wanted, or is a local pre-push hook enough?

---

## Re-verify

```bash
source .venv/bin/activate
pytest -m "not slow" -q -p no:cacheprovider --no-header        # H-1: 11 failed
ruff check . --statistics                                      # H-4/H-8: 40 errors
find vlm_photo_editor -name AGENTS.md | wc -l                  # H-8: 10
ls tests/unit/test_*.py | wc -l; ls tests/integration/test_*.py   # H-8: 17; 2 files
python agent_notes/utility_scripts/validate_okf.py             # strengths: 4/4 PASS
python3 -c "import json;a=json.load(open('.claude/settings.json'));print(len(a['permissions']['allow']),'deny' in a['permissions'])"   # H-2: 83 False
git ls-files | grep -E '^(CLAUDE.md|\.claude)'                 # H-3: empty
ls .git/hooks | grep -v sample; git config core.hooksPath      # H-4: empty
grep -rn "vlm_photo_editor\.\(ops\|background\)" vlm_photo_editor/agents vlm_photo_editor/planner   # H-5
wc -c plans/issues.md                                          # H-9: 156314
```
