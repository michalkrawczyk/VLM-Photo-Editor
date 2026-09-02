# Insights

Observations and conclusions from agent sessions that could improve future runs. Not task status,
not a restatement of a diff, not anything readable from code. One entry per durable fact.

---

## CLAUDE.md drifts from the bundle; the bundle is usually right

Discovered 2026-08-24. CLAUDE.md's Testing section claimed two pytest markers and "default run
excludes `slow`". `pyproject.toml` defines three (`slow`, `integration`, `e2e`) and its `addopts`
excludes **e2e**. `commands.md` had it correct the whole time — the inline copy in CLAUDE.md had
drifted from the file it was summarizing.

**Apply:** when CLAUDE.md and an `agent_notes/` file disagree on a verifiable fact, check the source
(`pyproject.toml`, the script) and fix CLAUDE.md. Duplicating a fact inline is what caused the
drift — prefer a pointer over a copy for anything that can change.

---

## A gitignore entry is not implied by a convention

Discovered 2026-08-24. CLAUDE.md instructed session scripts into `.tmp_scripts/` for a long time, but
that path was never added to `.gitignore` — only `agent_ignore/` was. Scratch files would have shown
up in `git status` and could have been committed.

**Apply:** any instruction that says "put throwaway output at path X" needs a matching `.gitignore`
line written at the same time. Check before trusting a documented scratch path.

---

## The Done Gate cannot go green today

Discovered 2026-08-24. `run_checks.sh` reports `ruff FAIL` on an unmodified tree — 48 errors, only 1
auto-fixable (mostly `E501` in prompt strings and deliberate `E402` lazy imports in Streamlit
modules). CLAUDE.md's T1 rule says "every BLOCK row PASS", which is unreachable.

**Apply:** a red `ruff` row after your change is not automatically your fault. Stash and re-run to
compare against the baseline before debugging. Baseline table and the interim passing condition
(no new errors in files your diff touched) are in [done_gate.md](done_gate.md). Cleaning the
baseline would make the gate honest again — worth doing as its own commit.

---

## mypy config is dead

`pyproject.toml` has `[tool.mypy] strict = true`, but mypy is not in `requirements_dev.txt`, not in
`.venv`, and no script runs it. `run_checks.sh` deliberately excludes it.

**Apply:** don't cite the strict-mypy config as evidence the codebase typechecks. It has never been
run clean. Typecheck status is unverified. Also see [commands.md](commands.md).
