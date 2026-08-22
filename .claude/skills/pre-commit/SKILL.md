---
name: pre-commit
description: "Run before every commit or PR: format, type check, tests. Use when committing code or opening a PR."
---

# Pre-Commit Checklist

```bash
bash agent_notes/utility_scripts/run_checks.sh --full && \
bash agent_notes/utility_scripts/cleanup.sh
```

- Checks: `ruff`, `black`, `isort`, `pydocstyle`, full `pytest` — every BLOCK row must be `PASS`
- `pydocstyle` is advisory (`WARN`); a `SKIP` row means the tool isn't installed — report it, don't call it green
- Cleanup: formats code, sorts imports, regenerates module map

**Before any PR merge:** search for `#@agent` markers and extract to `agent_notes/patterns/` before deleting.
