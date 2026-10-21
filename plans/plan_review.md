# Codebase Review Plan

Built from directory/structure listing only (names, sizes). No file contents read. Rationales are inferences from names and layout — confirm during review.

## Overview

Python package `vlm_photo_editor/` (~20 subpackages), plus `tests/`, `plans/`, `agent_notes/`, packaging files. Layered shape inferred from names:

- **Contracts:** `schema/` (plan, ops, op_catalog, recipe, prefs, report, batch, detection).
- **Foundations:** `secrets/`, `config/`, `models/`, `imageio/`, `recipe/`.
- **Execution:** `ops/` (executor, validator, mask) + `ops/backends/` (pil, cv, genai).
- **Planning:** `planner/` (compiler, repair), `templates/` (prompt text + `planner.py`), `agents/` (planner, critic, aggregator, edit_flow).
- **Perception:** `analysis/` (EXIF, image report, critic checks), `detection/` (YOLO-ONNX, MediaPipe, U2NetP).
- **genAI:** `background/` + `providers/` (google, openai, huggingface, replicate).
- **Orchestration:** `pipeline/` (batch, job queue, plan cache, cost router), `preferences/`.
- **UI:** `app/` (Streamlit `main.py`, state) + `app/components/`.
- **Tests:** unit (17 files), integration (2), e2e (3 + helpers), eval (harness, metrics, cases).

Structural hot spots (size / naming signals, unverified):

- Largest files: `app/main.py` (~45 KB), `app/components/settings.py` (~24 KB), `templates/planner.py` (~18 KB), `app/components/batch_review.py` (~15 KB), `pipeline/batch.py` (~14 KB), `ops/backends/pil_backend.py` (~13 KB), `agents/planner.py` (~13 KB), `detection/registry.py` (~13 KB), `schema/op_catalog.py` (~11 KB).
- Name collisions / overlap: three `registry.py` (config, models, detection); `planner` lives in `planner/`, `agents/planner.py` and `templates/planner.py`; `batch` in `schema/` and `pipeline/`; two `stubs.py` (`app/`, `ops/backends/`); `framing.py` in `templates/` and `app/components/`.
- Oddities: `app/tmp_layout.py` (temp-named module shipped in package); `background/generator.py` is tiny (~0.5 KB, likely thin shim); `background/providers/` has 4 vendor clients to keep in parity; `.env` exists at repo root (verify gitignored); `.tmp_scripts/` holds eval results.
- Per-module `AGENTS.md` absent for: `config`, `models`, `pipeline`, `preferences`, `recipe`, `templates`.

Review focus order (apply to every batch):

1. Bugs / correctness
2. Security / data-integrity risks
3. Code smells / maintainability
4. Performance
5. Over-engineered / unjustified functionality
6. UX/UI improvements

Batches ordered by risk and dependency: contracts and safety foundations first, UI and tests last. Mark a finished batch by appending ` [DONE]` to its heading.

---

## Batch 1: Schema contracts

**Files:** `vlm_photo_editor/schema/` — `__init__.py`, `plan.py`, `ops.py`, `op_catalog.py`, `recipe.py`, `prefs.py`, `report.py`, `batch.py`, `detection.py`, `AGENTS.md`

**Rationale:** Root dependency; every other layer consumes these models, so a flaw here propagates everywhere. `op_catalog.py` (~11 KB) is the largest and likely holds param specs, risk tiers and policy mapping that the planner and executor both rely on. Expect inconsistencies between catalog, `ops.py` and validator, loose field constraints, and accidental sibling imports.

**Review focus:**
1. Constraint gaps (ranges, enums, required fields), default drift, step-ID stability, risk-tier assignment correctness.
2. Fields that could carry secrets or absolute source paths into recipes.
3. Duplicate or overlapping models (`batch.py`, `report.py`, `detection.py`); schema versioning/migration story.
4. Over-broad catalog (ops no executor path can run).
5. Import hygiene: `schema/` must import nothing from siblings.

---

## Batch 2: Secrets, config and model registry

**Files:** `vlm_photo_editor/secrets/` (`store.py`, `redaction.py`, `AGENTS.md`), `vlm_photo_editor/config/` (`settings.py`, `registry.py`, `policy.py`), `vlm_photo_editor/models/registry.py`

**Rationale:** Security-critical foundation: key resolution (env → keyring → `.env`), log redaction, accept-mode and policy settings, model catalog. Small files but highest blast radius. Likely issues: redaction gaps (structlog path, exception tracebacks, repr of settings), key leakage into settings/session objects, and two registries (`config/registry.py`, `models/registry.py`) with overlapping responsibility.

**Review focus:**
1. Resolution order bugs, masked-display bugs, fallback behavior when keyring is unavailable.
2. Key exposure in logs, repr, error messages, recipes, session state; `.env` handling and gitignore.
3. Registry duplication; policy (Auto / PS-strict / No-PS) enforcement location.
4. Settings load cost / repeated parsing.
5. Unneeded abstraction in the registry layers.
6. Settings error messages surfaced to the UI.

---

## Batch 3: Image I/O and recipe persistence

**Files:** `vlm_photo_editor/imageio/` (`loaders.py`, `savers.py`, `container.py`, `AGENTS.md`), `vlm_photo_editor/recipe/` (`store.py`, `session.py`, `renderer.py`)

**Rationale:** Everything touching the original file and replay: RAW via rawpy, 16-bit handling, save paths, recipe write/read and re-render. Principle #1 (never overwrite source) lives here. Likely issues: path collision or overwrite on save, bit-depth/colorspace loss, ICC/EXIF handling, non-atomic recipe writes, and recipe replay not matching live execution.

**Review focus:**
1. Bit-depth/orientation/colorspace correctness; replay determinism; seed round-trip.
2. Source-overwrite paths, atomic writes, path traversal, symlinks, unsafe deserialization of recipes.
3. Duplicated load/convert code; session state held in recipe layer.
4. Full-resolution copies and repeated decode.
5. Container/session abstractions with a single user.
6. Save-failure and format feedback to the user.

---

## Batch 4: Ops executor, validator and mask

**Files:** `vlm_photo_editor/ops/` — `executor.py`, `validator.py`, `mask.py`, `constants.py`, `__init__.py`, `AGENTS.md`

**Rationale:** The deterministic core: `Executor.apply()` validates then dispatches OpGraph steps. Correctness here decides whether approved plans run as shown. Expect param-validation holes, op ordering/dependency bugs, mask-merge errors, error handling that swallows partial failures, and drift between validator rules and `schema/op_catalog.py`.

**Review focus:**
1. Validation completeness, dispatch coverage vs. catalog, mask math (feather, invert, bounds), partial-failure state.
2. Unvalidated execution paths; subject-pixel freeze enforcement; policy gating at execute time.
3. Duplicate constants/magic numbers across validator and catalog.
4. Redundant array copies in step loop.
5. Dead dispatch branches.
6. Per-step error messages usable in the UI.

---

## Batch 5: Ops backends (PIL / CV / genAI)

**Files:** `vlm_photo_editor/ops/backends/` — `pil_backend.py`, `cv_backend.py`, `genai_backend.py`, `stubs.py`

**Rationale:** Actual pixel operations. `pil_backend.py` (~13 KB) is the largest; expect per-op numeric bugs (clipping, dtype, channel order, 8- vs 16-bit), PIL-vs-numpy conversions that lose precision, and inconsistent behavior between PIL and CV paths for the same op. `genai_backend.py` bridges to background generation and must preserve frozen subject pixels and record model/prompt/seed.

**Review focus:**
1. Dtype/range/channel bugs, op-parameter semantics vs. catalog, backend-selection logic, mask handling.
2. Seed/prompt capture for genAI; compositing leaks into subject region; temp file handling.
3. Duplicated helpers between backends; stub vs. real parity.
4. Unnecessary uint8 round-trips, per-pixel Python loops, repeated conversions.
5. Ops implemented in two backends without need.
6. N/A unless op previews/latency are exposed.

---

## Batch 6: Planner compiler, repair and prompt templates

**Files:** `vlm_photo_editor/planner/` (`compiler.py`, `repair.py`, `AGENTS.md`), `vlm_photo_editor/templates/` (`planner.py`, `framing.py`, `background.txt`, `frame.txt`, `full_edit.txt`, `__init__.py`)

**Rationale:** Human plan → validated OpGraph, with repair of malformed VLM output, plus the prompt text that drives the VLM. `templates/planner.py` (~18 KB) is the biggest and likely mixes prompt building with logic; `repair.py` risks silently rewriting plans (violates principle #3). Expect prompt/catalog drift, brittle JSON repair, and planner-proposes-what-executor-can't-run bugs.

**Review focus:**
1. Step-ID stability, compile determinism, repair edge cases, policy-aware op filtering (planner/executor parity).
2. Prompt injection via filenames/EXIF/user text into prompts; secrets in prompts; silent rewrite of plans.
3. `templates/planner.py` size/responsibility, naming overlap with `planner/` and `agents/planner.py`; `templates/framing.py` vs `app/components/framing.py`.
4. Prompt size/token cost, repeated catalog serialization.
5. Repair heuristics that could be a stricter retry loop.
6. Plan wording clarity for the user.

---

## Batch 7: Agents (planner, critic, aggregator, edit flow)

**Files:** `vlm_photo_editor/agents/` — `planner.py`, `critic.py`, `aggregator.py`, `edit_flow.py`, `__init__.py`, `AGENTS.md`

**Rationale:** LangChain/LangGraph orchestration of VLM calls and the approve → compile → execute → critique loop. Likely issues: approval-gate bypass in some accept modes, unbounded regenerate loops, retry/timeouts missing, graph state carrying sensitive data, and critic results not feeding back safely.

**Review focus:**
1. Loop termination, accept-mode gating (`manual` / `auto_*` / `full_auto`), state transitions, error propagation.
2. Keys/PII in graph state or traces; unvalidated model output reaching the executor.
3. Overlap with `planner/` and `templates/`; hidden coupling to UI state.
4. Redundant VLM calls, missing plan cache use, serial calls that could batch.
5. Aggregator/critic layers that add little over simple functions.
6. Change-request loop feedback and progress reporting.

---

## Batch 8: Analysis and critic checks

**Files:** `vlm_photo_editor/analysis/` — `image_report.py`, `critic_checks.py`, `exif.py`, `__init__.py`, `AGENTS.md`

**Rationale:** Deterministic image statistics and post-edit checks that feed both planner and critic. Expect metric bugs (histogram clipping, color-space assumptions, thresholds hard-coded), EXIF parsing fragility (missing/corrupt tags, orientation), and checks whose thresholds are unjustified.

**Review focus:**
1. Metric math, threshold semantics, EXIF edge cases, 16-bit vs 8-bit inputs.
2. EXIF as untrusted input (huge/malformed fields, GPS/privacy leakage into prompts or reports).
3. Magic numbers; duplicated stats code with `ops/` or `detection/`.
4. Full-resolution analysis where a downscale suffices; repeated passes.
5. Checks that never change a decision.
6. Readability of report/critic output for users.

---

## Batch 9: Detection and segmentation

**Files:** `vlm_photo_editor/detection/` — `registry.py`, `_common.py`, `yolo_onnx_backend.py`, `mediapipe_backend.py`, `u2netp_backend.py`, `__init__.py`, `AGENTS.md`; asset dir `infer_models/yolo/`

**Rationale:** Model-backed subject/mask detection that determines which pixels are "frozen". `registry.py` (~13 KB) likely handles backend selection, fallbacks and caching. Expect letterbox/NMS coordinate bugs, optional-dependency import failures, model-load repeated per call, and silent fallbacks that change results between runs.

**Review focus:**
1. Coordinate transforms, NMS/threshold logic, mask resolution mismatch, fallback correctness, determinism across backends.
2. Model file integrity/path handling; untrusted model paths; ONNX provider selection.
3. Registry size/responsibilities; duplicated pre/post-processing across backends.
4. Session reuse, input resizing, thread safety, lazy loading.
5. Three backends — confirm each is justified and reachable.
6. Missing-model/dep messages shown in the UI.

---

## Batch 10: Background generation and providers

**Files:** `vlm_photo_editor/background/` (`composite.py`, `quality.py`, `generator.py`, `__init__.py`, `AGENTS.md`), `vlm_photo_editor/background/providers/` (`base.py`, `google_provider.py`, `openai_provider.py`, `huggingface.py`, `replicate.py`, `__init__.py`)

**Rationale:** The only genAI path; touches API keys, network, cost, and subject-pixel freeze. Four vendor clients behind `base.py` will drift in error handling, timeouts, seed support and key handling. `composite.py` is where frozen pixels must be enforced; `quality.py` gates outputs.

**Review focus:**
1. Composite masking/feathering, seed capture and reproducibility, quality-gate logic, provider response parsing.
2. Key handling at call time only; keys in exceptions/logs/URLs; download of provider-returned URLs (SSRF, size limits, temp files); per-run genAI ceiling enforced.
3. Provider duplication; `generator.py` thin shim; inconsistent error types.
4. Timeouts, retries/backoff, streaming large images, redundant encodes.
5. Providers not reachable from settings or lacking tests.
6. Progress/cost display and failure messages.

---

## Batch 11: Pipeline (batch) and preferences

**Files:** `vlm_photo_editor/pipeline/` (`batch.py`, `job_queue.py`, `plan_cache.py`, `cost_router.py`), `vlm_photo_editor/preferences/store.py`

**Rationale:** Batch orchestration, caching, routing and learned preferences — all stateful. `batch.py` (~14 KB) likely mixes queueing, execution and result bookkeeping. Expect race conditions, cache-key collisions (stale plans reused across changed prompts/models/policy), partial-batch failure handling, and non-atomic preference writes.

**Review focus:**
1. Cache keying/invalidation, per-run ceiling counting, failure isolation per image, `full_auto` post-run review enforcement.
2. Concurrent writes, preference file integrity, learned prefs inspectable/editable, path handling for batch outputs (no source overwrite).
3. `batch.py` size; overlap with `schema/batch.py`; module lacks `AGENTS.md`.
4. Parallelism, queue overhead, cache hit rates, repeated disk reads.
5. `cost_router` / `job_queue` — verify they are used and justified.
6. Batch progress, cancel/resume, preference editing affordances.

---

## Batch 12: App core (Streamlit entry and state)

**Files:** `vlm_photo_editor/app/` — `main.py`, `state.py`, `stubs.py`, `tmp_layout.py`, `__init__.py`, `AGENTS.md`

**Rationale:** `main.py` (~45 KB) is the largest file and likely wires the whole workflow: upload → plan → approve → execute → save. Expect god-function structure, Streamlit rerun/session-state bugs, business logic leaking into UI, approval-gate paths per accept mode, and `tmp_layout.py` / `stubs.py` being leftover scaffolding.

**Review focus:**
1. Rerun-induced double execution, stale session state, approval gate not enforced on every path, error handling around long calls.
2. Secrets in `st.session_state`; temp upload files; save path choice vs. source overwrite; unsanitized filenames.
3. Split `main.py` by workflow stage; remove or rename `tmp_layout.py`; stubs shipped in prod package.
4. Recompute on every rerun, missing `st.cache_*`, large images in session state.
5. Dead or temporary UI code paths.
6. Flow clarity, progress feedback, error visibility, undo/compare affordances.

---

## Batch 13: App components

**Files:** `vlm_photo_editor/app/components/` — `settings.py`, `batch_review.py`, `plan_view.py`, `prefs_panel.py`, `canvas.py`, `preview.py`, `upload.py`, `candidate_picker.py`, `character_focus.py`, `framing.py`, `__init__.py`

**Rationale:** UI building blocks. `settings.py` (~24 KB) probably handles keys/models/policy and is the most sensitive UI file; `batch_review.py` (~15 KB) gates "Save All" after `full_auto` runs. Expect long render functions, widget-key collisions, and masked-key display bugs.

**Review focus:**
1. Widget key collisions, state mutations during render, "Save All" gating, plan edit/approve correctness.
2. Key input/masking, echoing keys back into state or logs; upload validation (type, size, decompression bombs).
3. `settings.py` split by concern; duplicate UI helpers; `framing.py` naming overlap with `templates/framing.py`.
4. Re-encoding previews each rerun; large canvas payloads.
5. `candidate_picker` / `character_focus` — confirm used from `main.py`.
6. Layout, labels, empty/error states, keyboard flow, accessibility, before/after comparison.

---

## Batch 14: Unit tests

**Files:** `tests/unit/` — `test_schema.py`, `test_op_catalog.py`, `test_ops.py`, `test_planner.py`, `test_edit_flow.py`, `test_analysis.py`, `test_background.py`, `test_imageio.py`, `test_recipe.py`, `test_prefs.py`, `test_secrets.py`, `test_framing.py`, `test_batch_processing.py`, `test_tmp_layout.py`, `test_p9_critic.py`, `test_p10_hardening.py`, `test_p13_character_focus.py`; `tests/fixtures/` (images, prompts, schemas)

**Rationale:** ~8.4k lines. Phase-named files (`p9`, `p10`, `p13`) suggest tests organized by milestone, not module — likely duplicated coverage and gaps for `detection/`, `pipeline/plan_cache`, `config/`, `models/`, providers (no `test_detection`/`test_config`/`test_pipeline` visible). Weak assertions or mocks hiding failures are the main risk.

**Review focus:**
1. Tests that pass for wrong reasons; assertions too weak; wrongly mocked failures; skipped/xfail.
2. Security tests: redaction, key non-leak, source-overwrite guard; fixture files containing real keys or personal data.
3. Phase-named files → module-named; for-loops instead of `parametrize`; fixture duplication.
4. Slow tests not marked `slow`; heavy image fixtures.
5. Tests of removed/unused functionality (`test_tmp_layout.py` tracks a temp module).
6. N/A.

---

## Batch 15: Integration, e2e and eval tests

**Files:** `tests/integration/` (`test_batch_modes.py`, `test_p8_5_mvp_gate.py`), `tests/e2e/` (`conftest.py`, `_helpers.py`, `test_batch.py`, `test_full_edit_and_framing.py`, `artifacts/`, `models/`), `tests/eval/` (`harness.py`, `metrics.py`, `compare.py`, `cases.py`, `test_oracle_eval.py`, `test_vlm_eval.py`), `.tmp_scripts/eval_results/`

**Rationale:** Real-model and cross-layer checks; the eval harness is custom infrastructure (harness/metrics/compare) that may be over-built. e2e hits real providers or models (cost, keys). Expect flaky/nondeterministic assertions, artifacts committed or leaking into the repo, and eval metrics of questionable validity.

**Review focus:**
1. Metric correctness in `metrics.py`/`compare.py`; nondeterminism; tests depending on local models or network.
2. Keys required/printed by e2e; artifacts and eval results containing personal images or secrets; check what is tracked by git.
3. Duplicate helpers across `e2e/_helpers.py`, `eval/harness.py`, unit fixtures.
4. Eval runtime/cost; model loading per test.
5. Harness features not used by any test.
6. N/A.

---

## Batch 16: Packaging, infrastructure and documentation

**Files:** `pyproject.toml`, `requirements*.txt` (base, dev, anthropic, openai, huggingface, llamacpp, mediapipe, ollama, onnxruntime), `packages.txt`, `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, `.env` (existence/ignore status only), `RUNBOOK.md`, `README.md`, `plans/` (4 files), `agent_notes/` (+ `utility_scripts/`), `.claude/` (commands, skills), `.vscode/`, `samples/`

**Rationale:** Cross-cutting config. Many split requirements files risk drift from `pyproject.toml`; the Dockerfile may bake in secrets or run as root; docs and agent notes may disagree with code. Low code risk, high operational/security risk if `.env` or large binaries are tracked.

**Review focus:**
1. Version pin conflicts, missing extras, entry points, Docker build correctness, notes-vs-code contradictions.
2. `.env` ignored and untracked; secrets in image layers/history; non-root container; large model/sample binaries tracked; `.dockerignore` coverage.
3. Requirements duplication vs. `pyproject.toml` extras; stale plans; doc sprawl.
4. Docker layer caching, image size, heavy default deps.
5. Optional-backend requirement files nobody uses.
6. README/RUNBOOK onboarding clarity, first-run experience, error-message docs.
