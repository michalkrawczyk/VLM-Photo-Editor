# agent_notes/ Index

Project notes bundle. Not `.agent_notes/` — this project's established directory name, referenced by path throughout scripts and docs; kept as-is.

Read at task start: `commands.md`, `module_map.md`. Read on demand: everything else, per its trigger.

| File | Holds | Read when |
|---|---|---|
| `commands.md` | Verified setup/run/test/lint/typecheck commands | Before running anything |
| `module_map.md` | How to generate/view/search the code index | Locating classes/methods/functions, exploring structure, before grep |
| `goal.md` | One-paragraph pitch, accept modes, batch semantics | Quick orientation |
| `description.md` | Full product description, target user, MVP acceptance criteria, out-of-scope | Scoping a feature; checking if something is out-of-scope |
| `stack.md` | Tech stack choices with rationale + rejected alternatives per concern | Choosing a library; before adding a dependency |
| `structure.md` | Module list + file tree for `vlm_photo_editor/` and `tests/` | Orientation; finding where a file should live |
| `future_improvements.md` | Deferred features/libraries, why-deferred, adoption trigger | Considering something explicitly out of current scope |
| `generate_module_map.py` | Regenerates `agent_ignore/module_map.json` | See `module_map.md` |
| `view_module_map.py` | Formats the map for reading | See `module_map.md` |
| `search_module_map.py` | Searches the map by name/type | See `module_map.md` |
| `utility_scripts/run_checks.sh` | Done Gate T1/T3: `ruff`, `black`, `isort`, `pydocstyle`, `pytest` | Before claiming any code task done |
| `utility_scripts/cleanup.sh` | End-of-session: `black`, `isort`, regenerate module map | End of a work session |
| `utility_scripts/run_all_reviews.sh` | Loops `/batch_review` until `plans/plan_review.md` batches are all `[DONE]` | Running the batch plan-review loop |

Per-module code rules: `vlm_photo_editor/<module>/AGENTS.md`, where present (see `structure.md` for the current list) — not part of this bundle, but linked from it.

No `gotchas/`, `decisions/`, `conventions.md`, `glossary.md`, `testing.md`, or `log.md` exist yet — add them when there's real, non-speculative content, not preemptively.
