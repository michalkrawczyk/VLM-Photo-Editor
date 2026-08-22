# Commands

Verified against `pyproject.toml`, `README.md`, `RUNBOOK.md`. No Makefile, no CI config exists — these are the only source of truth.

## Setup

```
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env               # API keys
```

Optional provider adapters (pick per `agent_notes/stack.md`):
```
pip install -r requirements-openai.txt
pip install -r requirements-huggingface.txt
pip install -r requirements-ollama.txt
pip install -r requirements-llamacpp.txt
pip install -r requirements-mediapipe.txt
pip install -r requirements-onnxruntime.txt
```

## Run

```
streamlit run vlm_photo_editor/app/main.py
streamlit run vlm_photo_editor/app/main.py --server.port 8502   # alternate port
```

No console_scripts entry point exists — the app is only runnable via `streamlit run`, not an installed CLI command.

Docker:
```
docker build -t vlm-photo-editor .
docker run -p 8501:8501 -e ANTHROPIC_API_KEY=... -e REPLICATE_API_TOKEN=... vlm-photo-editor
```

## Test

```
pip install -r requirements_dev.txt
pytest                                              # everything except e2e (addopts: -m "not e2e")
pytest -m "not slow"                                # default/fast run
pytest -m integration                               # integration only
pytest -m slow                                      # live-API integration tests (needs ANTHROPIC_API_KEY)
pytest --cov=vlm_photo_editor --cov-report=term-missing
```

Markers (`pyproject.toml` `[tool.pytest.ini_options]`): `slow` (long-running, deselect with `-m "not slow"`), `integration` (requires full pipeline), `e2e` (live-browser Playwright tests, also tagged `slow` — deselected by default via `addopts = ["-m", "not e2e"]`; a `-m` on the command line overrides that, so `pytest -m e2e` still selects them).

### E2E (Playwright, live browser)

```
playwright install chromium                         # one-time browser install
pytest -m e2e tests/e2e/ -v                          # real Anthropic API + real MediaPipe detection
```
Drives the real Streamlit app (`streamlit run`, subprocess) with real API calls — costs money, needs `ANTHROPIC_API_KEY` in `.env`. First run downloads a ~4.6MB MediaPipe object-detector model to `tests/e2e/models/` (gitignored); set `E2E_MEDIAPIPE_MODEL_PATH` to point at an existing `.tflite` file to skip the download. Screenshots per test checkpoint land in `tests/e2e/artifacts/` (gitignored) — read them after a run to visually confirm behavior. A failing test also drops `<test>_FAIL.png`, `<test>_FAIL.html`, and `<test>_FAIL.serverlog.txt` there.

## Lint / format / typecheck

All checks in one run (`ruff`, `black`, `isort`, `pydocstyle`, `pytest`), status table + exit 1 if any blocking step fails:
```
bash agent_notes/utility_scripts/run_checks.sh            # fix mode + pytest -m "not slow"
bash agent_notes/utility_scripts/run_checks.sh --check    # read-only, modifies nothing
bash agent_notes/utility_scripts/run_checks.sh --full     # full pytest
```
Runs every step even after a failure — one invocation gives the whole picture. `pydocstyle` is advisory (`WARN`, never blocks); a tool missing from `PATH` reports `SKIP`, never `PASS`. `PKG` env var overrides the `pydocstyle` target dir (default `vlm_photo_editor`).

Individual tools, order per `RUNBOOK.md`:
```
ruff check --fix .
black .
isort .
pydocstyle --convention=google vlm_photo_editor
```

Check-only (no changes):
```
ruff check .
black --check .
isort --check .
```

`mypy` has a `[tool.mypy]` config in `pyproject.toml` (`strict = true`, `python_version = "3.12"`) but is **not installed** (absent from `requirements_dev.txt` and `.venv`), and no script runs it — `run_checks.sh` deliberately excludes it. The config is currently dead. Typecheck status: unverified, never run clean.

## Config reference

- `[tool.black]`, `[tool.ruff]`, `[tool.isort]`: `line-length = 100`, target `py312`.
- `[tool.ruff.lint]`: `select = ["E", "F", "W", "I"]`.
- `pydocstyle` has no `[tool.pydocstyle]` section; the convention is passed on the CLI (`--convention=google`) by `run_checks.sh`. Baseline on `vlm_photo_editor/`: 236 violations (211 are missing-docstring `D100`–`D107`), which is why it is advisory and not blocking.
