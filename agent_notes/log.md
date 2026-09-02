# Log

Chronological, append-only. One dated line per nontrivial change to the bundle or to project
conventions. Newest at the bottom.

---

- 2026-08-24 — Restructured CLAUDE.md: Done Gate, Testing, Git Commits, and Subagents moved to
  `done_gate.md`, `testing.md`, `git.md`, `subagents.md`, leaving 4-6 line stubs inline (trigger +
  prohibitions + link). Added `insights.md` and `log.md`. Fixed two factual errors in CLAUDE.md —
  pytest markers (`e2e` was missing; default run excludes e2e, not slow) and `.tmp_scripts/`, which
  was documented as scratch space but absent from `.gitignore` (now added). CLAUDE.md 267 → 227 lines.
- 2026-08-24 — Recorded that the Done Gate's `ruff` row is red on a clean tree (48 pre-existing
  errors, 1 auto-fixable). Baseline table + the interim passing condition are in `done_gate.md`.
- 2026-08-24 — `run_checks.sh` gained scoped-pytest flags (`[PATH ...]`, `-k`/`--match`,
  `-m`/`--marker`, `--ignore`, `--short [N]`); pytest moved off the shared `run()` path so `--short`
  can pipe to `tail` while keeping the real exit code via `PIPESTATUS[0]`. CLAUDE.md, `done_gate.md`,
  and `commands.md` updated to match; full flag list lives in `done_gate.md`, the other two point at it.
- 2026-08-24 — Added `utility_scripts/validate_okf.py`: checks bundle links resolve, `index.md` has a
  row per file (and no row without a file), and every backticked `agent_notes/…` path in CLAUDE.md
  exists. No frontmatter checks — this bundle deliberately has none, so the validator enforces that
  choice instead of the OKF spec. Standalone; not wired into `run_checks.sh` or `cleanup.sh`.
  Also fixed two CLAUDE.md drifts it now guards: the Done Gate's "every BLOCK row PASS" (unreachable
  while the ruff baseline is 48 errors) and the hand-copied "67/75 DoD checkboxes" (now a pointer).
- 2026-08-24 — Fixed the `Stop` hook in `.claude/settings.json`: it pointed at
  `/media/tk/Programming1/…` (nonexistent — repo is `/media/tk/Programming/…`) and hid the failure
  behind `2>/dev/null`, so `cleanup.sh` had never run. Now `$CLAUDE_PROJECT_DIR`-relative, stderr
  visible. Evidence it was dead: `agent_ignore/module_map.json` was ten days stale.
  ~15 stale `Programming1` entries remain in `permissions.allow` — dead weight, not breakage.
