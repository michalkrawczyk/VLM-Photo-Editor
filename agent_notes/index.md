# agent_notes/ Index

Project notes bundle. Not `.agent_notes/` — this project's established directory name, referenced by path throughout scripts and docs; kept as-is.

Read at task start: `commands.md`, `module_map.md`. Read on demand: everything else, per its trigger.

| File | Holds | Read when |
|---|---|---|
| `commands.md` | Verified setup/run/test/lint/typecheck commands | Before running anything |
| `module_map.md` | How to generate/view/search the code index | Locating classes/methods/functions, exploring structure, before grep |
| `done_gate.md` | T0–T3 tier ladder, `run_checks.sh` flags, PASS/FAIL/WARN/SKIP semantics, report format | Task complete; before claiming any code task done |
| `testing.md` | Marker semantics, fixture map, test layout, extend-don't-create rule | Before writing or changing a test |
| `git.md` | Conventional Commits detail, types, never-commit list | Before committing |
| `subagents.md` | Delegate-when/never lists, brief format, result handling | Before delegating to a subagent |
| `goal.md` | One-paragraph pitch, accept modes, batch semantics | Quick orientation |
| `description.md` | Full product description, target user, MVP acceptance criteria, out-of-scope | Scoping a feature; checking if something is out-of-scope |
| `stack.md` | Tech stack choices with rationale + rejected alternatives per concern | Choosing a library; before adding a dependency |
| `structure.md` | Module list + file tree for `vlm_photo_editor/` and `tests/` | Orientation; finding where a file should live |
| `insights.md` | Cross-session observations/conclusions that improve future runs | Session end; before trusting a documented fact that looks stale |
| `log.md` | Append-only dated history of bundle/convention changes | Rarely; write on a nontrivial change |
| `utility_scripts/generate_module_map.py` | Regenerates `agent_ignore/module_map.json` | See `module_map.md` |
| `utility_scripts/view_module_map.py` | Formats the map for reading | See `module_map.md` |
| `utility_scripts/search_module_map.py` | Searches the map by name/type | See `module_map.md` |
| `utility_scripts/run_checks.sh` | Done Gate T1/T3: `ruff`, `black`, `isort`, `pydocstyle`, `pytest` | Before claiming any code task done |
| `utility_scripts/cleanup.sh` | End-of-session: `black`, `isort`, regenerate module map | End of a work session |
| `utility_scripts/validate_okf.py` | Checks bundle links resolve, `index.md` covers every file, CLAUDE.md's `agent_notes/` pointers exist | After adding, renaming, or removing a bundle file |

Per-module code rules: `vlm_photo_editor/<module>/AGENTS.md`, where present (see `structure.md` for the current list) — not part of this bundle, but linked from it.

No `gotchas/`, `decisions/`, `conventions.md`, or `glossary.md` exist yet — add them when there's
real, non-speculative content, not preemptively. This bundle uses no YAML frontmatter; keep new
files matching the existing plain-markdown style.
