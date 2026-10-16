# Testing

Read before adding a test. Commands live in [commands.md](commands.md); this file is the how and
where.

## Extend > create

Grep existing coverage before opening a new test file. Check whether the method under test already
fits an existing pipeline test — most units are already exercised through one.

Fewer test functions, broader coverage. `@pytest.mark.parametrize` — **never** a `for` loop over
cases; a loop reports one failure and hides the rest.

Merge related assertions (schema + round-trip + error case) into one test.

Assert behavior, not call counts, unless the call *is* the contract (e.g. "planner must not call the
executor").

## Markers

Defined in `pyproject.toml` `[tool.pytest.ini_options]`:

| Marker | Means | Select / deselect |
|---|---|---|
| `slow` | Long-running, incl. live-API integration (needs `ANTHROPIC_API_KEY`) | `-m slow` / `-m "not slow"` |
| `integration` | Requires the full pipeline | `-m integration` |
| `eval` | Planner/ops quality scored by `ImageReport` metric deltas on synthetic cases (`tests/eval/`). Oracle tier is cheap and runs in the gate; the VLM tier is also `slow` and needs `EVAL_VLM=1` (paid) | `-m eval` |
| `e2e` | Live-browser Playwright against a real Streamlit server; real API calls + real MediaPipe. Also tagged `slow` | `-m e2e` |

**Default-run gotcha.** `addopts = ["-m", "not e2e"]` — plain `pytest` runs everything **except
e2e**, not except slow. A `-m` on the command line overrides `addopts` entirely, so `pytest -m e2e`
still selects them. The fast gate run is an explicit `pytest -m "not slow"` (`run_checks.sh`), not a
default. CLAUDE.md previously stated this backwards.

## Layout

```
tests/
├── unit/          15 files, one per subsystem (test_schema.py, test_ops.py, test_planner.py,
│                  test_batch_processing.py, …) plus phase-scoped files: test_p9_critic.py,
│                  test_p10_hardening.py, test_p13_character_focus.py
├── integration/   package exists, currently empty (only __init__.py) — integration-marked tests
│                  live in unit/ today
├── eval/          cases.py (synthetic tagged cases + oracle ops), metrics.py, harness.py,
│                  test_oracle_eval.py, test_vlm_eval.py (opt-in), compare.py
│                  (`python -m tests.eval.compare a.json b.json` -> pass-rate/steps/repairs/latency deltas + flips)
├── e2e/           conftest.py, _helpers.py, test_full_edit_and_framing.py
└── fixtures/      static data, not pytest fixtures
    ├── face_portrait.jpg
    ├── prompts/base_prompt_full_mode.txt
    └── schemas/sample_opgraph.json, sample_plan.json, sample_recipe.json
```

New unit test for an existing subsystem → extend that subsystem's `test_*.py`. New test for a build-
plan phase's behavior → the phase file, if one exists.

## Fixtures

There is **no root `conftest.py`**. The only one is `tests/e2e/conftest.py`, all session-scoped:

| Fixture | Gives |
|---|---|
| `sample_image_jpg` / `sample_image_png` | `Path` to a test image |
| `screenshot_dir` | `Path` for per-checkpoint screenshots |
| `mediapipe_model_path` | `.tflite` detector; downloads ~4.6MB on first run unless `E2E_MEDIAPIPE_MODEL_PATH` is set |
| `mediapipe_usable` | `bool` guard for tests needing real detection |
| `streamlit_server` | Base URL of a live `streamlit run` subprocess |

Unit tests build their own inputs from `tests/fixtures/` — add static data there rather than
inventing a shared conftest.

## E2E specifics

Costs money (real Anthropic API) and needs `ANTHROPIC_API_KEY` in `.env` plus a one-time
`playwright install chromium`. Screenshots land in `tests/e2e/artifacts/` (gitignored) — read them
after a run to confirm behavior visually. A failure also drops `<test>_FAIL.png`, `<test>_FAIL.html`,
and `<test>_FAIL.serverlog.txt` there.

## Scratch

Prefer pytest over `python -c` and shell scripts. Session-written scripts → `.tmp_scripts/`
(gitignored, never imported by `vlm_photo_editor/`). Delete at task end. Ran it twice → it should
have been a pytest.

See also: [done_gate.md](done_gate.md) · [commands.md](commands.md)
