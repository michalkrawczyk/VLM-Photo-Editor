---
name: pre-commit
description: "Run before every commit or PR: format, type check, tests. Use when committing code or opening a PR."
---

# Pre-Commit Checklist

```bash
bash agent_notes/utility_scripts/cleanup.sh && \
mypy vlm_photo_editor/ --strict && \
pytest tests/ -v --cov=vlm_photo_editor --cov-report=term-missing
```

- Cleanup: formats code, sorts imports, regenerates module map
- Mypy: all type errors must resolve before committing
- Pytest: >80% coverage on new code

**Before any PR merge:** search for `#@agent` markers and extract to `agent_notes/patterns/` before deleting.
