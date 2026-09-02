# Git Commits

Conventional Commits. Subject ≤50 chars (hard cap 72). Imperative mood. No trailing period.

```
<type>(<scope>): <summary>
```

Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `chore`, `build`, `ci`, `style`, `revert`.

Scope is the module or area — `planner`, `ops`, `imageio`, `schema`, `app`, `claude`, `agent_notes`.
Omit it when the change is genuinely repo-wide.

Body only for non-obvious why, breaking changes, migration notes, `Closes #N`. Wrap at 72.

No AI attribution. No emoji.

## Never commit

- Secrets of any kind — `.env`, API keys, tokens. Keys live in env → OS keyring → gitignored `.env`.
- Generated files — `agent_ignore/` (holds `module_map.json`), `*.egg-info/`, `__pycache__/`.
- Session scratch — `.tmp_scripts/`.
- Binaries and model weights — `tests/e2e/models/`, `tests/e2e/artifacts/`.

All of the above are gitignored; if one shows up in `git status`, the ignore rule is wrong — fix the
rule, don't commit the file.

## Gate

T3 changes (schema, migration, public API, dependency, config) need human confirm before commit.
See [done_gate.md](done_gate.md). Never `--no-verify`.

## Examples

```
feat(planner): add step-ID stability check
fix(imageio): reject save path equal to source
docs(agent_notes): correct pytest marker defaults
refactor(ops): extract mask validation from executor
```
