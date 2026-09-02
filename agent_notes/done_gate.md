# Done Gate

Tier ladder run before claiming any task done. Pick the tier by what the diff touches, run every
step of that tier and all tiers below it.

## T0 — docs only

Saved. Nothing to run.

## T1 — any code

1. `bash agent_notes/utility_scripts/run_checks.sh` → every `BLOCK` row `PASS`
2. Every changed line traces to the request

## T2 — behavior change

T1, plus:

3. Test fails on old code, passes on new — state how you verified it
4. No leftover TODO or commented-out code

## T3 — schema, migration, public API, dependency, config

T2, plus:

5. `bash agent_notes/utility_scripts/run_checks.sh --full` green
6. Rollback path, one line
7. Human confirm before commit

## run_checks.sh semantics

Prefix each with `bash agent_notes/utility_scripts/run_checks.sh`:

```
                        # fix mode: ruff --fix, black, isort, pydocstyle, pytest -m "not slow"
--check                 # read-only, modifies no file
--full                  # drop the "not slow" filter (unless -m given)
tests/unit              # scope pytest to a path; default tests/, else test/, else pytest discovery
-k EXPR                 # pytest -k EXPR  (long form: --match)
-m integration          # override the default "not slow" marker  (long form: --marker)
--ignore tests/e2e      # pytest --ignore; repeatable
--short 40              # tail pytest output to last 40 lines; also --short=40, bare --short = 40
```

Flags combine: `run_checks.sh --check -m integration --short tests/unit`.

Runs every step even after a failure — one invocation gives the whole picture. Exit 0 if every
`BLOCK` step passed, 1 if any failed, 2 on bad usage. Bad usage = unknown `-flag`, missing argument
to `-k`/`-m`/`--ignore`, non-numeric `--short` value.

Two gotchas:

- **`--short` truncates pytest only.** `ruff`/`black`/`isort`/`pydocstyle` are never piped, and the
  script's `==> Summary` table prints after the pipe — so the status table is never cut and the
  exit code is real (recovered via `PIPESTATUS[0]`, not the pipe's status). The table is the
  evidence to cite, not the scrollback.
- **A scope that selects nothing still reports `FAIL`.** pytest exits 5 on "no tests collected", and
  the script reads any non-zero as `FAIL`. A typo'd `-k` looks identical to a broken test — check the
  `collected N items / N deselected / 0 selected` line before believing the row.
- **`--full` is not "run e2e too".** It only drops the `not slow` filter. With no `-m`, pytest's
  `addopts = ["-m", "not e2e"]` still applies. `-m MARKER` wins over `--full`.

Row severities:

| Row | Severity | Meaning |
|---|---|---|
| `PASS` | — | Step succeeded |
| `FAIL` | blocking | Gate is red |
| `WARN` | advisory | Only `pydocstyle` produces this; **never** blocks |
| `SKIP` | advisory | Tool not on `PATH` — **not** a pass; say "unverified" |

`pydocstyle` is advisory because the baseline on `vlm_photo_editor/` is 236 violations (211 of them
missing-docstring `D100`–`D107`). `PKG` env var overrides its target dir.

## Known red baseline (as of 2026-08-24)

The `ruff` row is **FAIL on a clean tree** — 48 pre-existing errors across 12 files, and only 1 is
auto-fixable, so neither fix mode nor `--check` clears it:

| Code | Count | Note |
|---|---|---|
| `E501` line too long | 23 | Mostly long prompt strings in `templates/`, `schema/op_catalog.py` |
| `E402` import not at top | 20 | Deliberate lazy imports in Streamlit `app/` modules |
| `F841` unused local | 2 | `tests/unit/test_ops.py:465`, `background/providers/huggingface.py:174` |
| `F821` undefined name | 2 | `app/main.py:45,67` — forward refs already carrying `# type: ignore[name-defined]`; false positives |
| `I001` unsorted imports | 1 | The one auto-fixable error |

So "every BLOCK row PASS" is currently unreachable. Until the baseline is cleaned: run the gate,
diff the error count against this table, and treat **no new errors in files your diff touched** as
the passing condition. Say so explicitly in the report rather than claiming green.

Scoping flags (`PATH`, `-k`, `-m`, `--ignore`, `--short`) reach pytest only — they speed the test
row up, they do nothing for the red `ruff` row.

`mypy` is **not** part of the gate. `[tool.mypy] strict = true` exists in `pyproject.toml` but the
tool is not installed and no script runs it — see `commands.md`.

## Reporting

```
Changed: … | Ran: cmd → result | Assumptions: … | Not done: …
```

No green claim without command output. Unverified → say "unverified".
Pre-existing failure blocks the gate → report it, proceed only if unrelated to the diff.

See also: [commands.md](commands.md) · [testing.md](testing.md) · [git.md](git.md)
