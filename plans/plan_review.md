# Codebase Review Plan

Batches derived from directory structure only (module/layer boundaries), not file content. Line counts noted for sizing context. Excludes caches (`.pytest_cache/`, `.ruff_cache/`), build artifacts (`vlm_photo_editor.egg-info/`), and binary/data fixtures.

## Overview

`vlm_photo_editor/` implements the Planner→Compiler→Executor→Recipe pipeline described in CLAUDE.md: a VLM proposes a human-readable edit plan, a compiler turns it into a validated `OpGraph`, a deterministic executor (imaging libs + optional genAI/Photoshop backends) runs it, and results are captured as a replayable `Recipe`. Supporting modules cover schema contracts, image I/O, subject/background detection, secrets handling, config/policy, batch pipeline orchestration, user preference learning, and a Streamlit app UI. `tests/` mirrors most modules with unit tests; a `plans/`, `agent_notes/`, and `.claude/` layer hold docs, build-plan tracking, and Claude Code tooling (commands, skills). Per-module `AGENTS.md` files (in `agents/`, `app/`, `background/`, `detection/`, `ops/`, `planner/`, `schema/`, `secrets/`) suggest each layer's invariants are already documented, which review should cross-check against actual code.

## Batch 1: Schema & Contracts [DONE]

**Files:** `vlm_photo_editor/schema/__init__.py`, `schema/plan.py`, `schema/ops.py`, `schema/op_catalog.py`, `schema/batch.py`, `schema/detection.py`, `schema/prefs.py`, `schema/recipe.py`, `schema/AGENTS.md`

**Rationale:** Per CLAUDE.md this is the root dependency — "schema imports nothing from siblings" — so every other module's correctness depends on these Pydantic models being right. `op_catalog.py` is untracked/new (per git status) and paired with a new `tests/unit/test_op_catalog.py`, making it the most likely spot for incomplete validation or drift from `ops/constants.py`.

**Review focus:** correctness of validation rules and required/optional fields; whether the "schema imports nothing from siblings" boundary is actually honored; consistency between `op_catalog.py` and the ops layer it presumably mirrors; over-engineered field/validator proliferation.

## Batch 2: Planning Layer (Planner Agent → Templates → Compiler) [DONE]

**Files:** `vlm_photo_editor/agents/__init__.py`, `agents/planner.py`, `agents/edit_flow.py`, `agents/critic.py`, `agents/aggregator.py`, `agents/AGENTS.md`, `vlm_photo_editor/planner/__init__.py`, `planner/compiler.py`, `planner/AGENTS.md`, `vlm_photo_editor/templates/__init__.py`, `templates/planner.py`, `templates/framing.py`, `templates/background.txt`, `templates/frame.txt`, `templates/full_edit.txt`

**Rationale:** These form one pipeline stage — prompt templates feed the VLM planner agent, whose output the compiler turns into an `OpGraph`, with critic/aggregator scoring results. `templates/planner.py` (215 lines) and `planner/compiler.py` (219 lines, modified per git status) are the largest files here and the most likely to contain step-ID handling bugs given the "step-IDs are stable, never rewritten" invariant.

**Review focus:** step-ID stability through compilation; planner/executor op parity (planner must only propose ops the compiler/executor can run); prompt-injection or unsanitized template interpolation; correctness of critic/aggregator scoring logic; maintainability of the templating approach.

## Batch 3: Ops Execution Engine [DONE]

**Files:** `vlm_photo_editor/ops/__init__.py`, `ops/constants.py`, `ops/executor.py`, `ops/mask.py`, `ops/validator.py`, `ops/AGENTS.md`, `ops/backends/__init__.py`, `ops/backends/cv_backend.py`, `ops/backends/pil_backend.py`, `ops/backends/genai_backend.py`, `ops/backends/stubs.py`

**Rationale:** The deterministic executor plus its pluggable backends (OpenCV, PIL, genAI, stubs) — the layer that must validate every `Op` against schema before running it and must never overwrite source images. `constants.py` and `validator.py` are both modified per git status alongside the new `op_catalog.py` in Batch 1, so cross-checking those two changes against each other is a priority.

**Review focus:** `Executor.apply()` validation is never bypassed; subject-pixel freezing during masked region edits; backend selection logic matches active policy (Auto/PS-strict/No-PS); mask math correctness; performance of per-op image copies.

## Batch 4: Image I/O [DONE]

**Files:** `vlm_photo_editor/imageio/__init__.py`, `imageio/container.py`, `imageio/loaders.py`, `imageio/savers.py`, `imageio/AGENTS.md`

**Rationale:** Small, self-contained module enforcing the single most important product invariant — "originals are never altered, saves always write a new file." Also the designated rawpy (not PIL) boundary for RAW files.

**Review focus:** any code path that could write back to the source path; correct rawpy usage for RAW vs Pillow for standard formats; bit-depth/color-space handling in `container.py`.

## Batch 5: Detection Backends [DONE]

**Files:** `vlm_photo_editor/detection/__init__.py`, `detection/_common.py`, `detection/mediapipe_backend.py`, `detection/u2netp_backend.py`, `detection/yolo_onnx_backend.py`, `detection/AGENTS.md`

**Rationale:** Three interchangeable subject/mask detection backends (mediapipe, u2netp, yolo-onnx) behind a shared `_common.py` interface — a natural boundary to check for consistent output contracts across backends.

**Review focus:** output-format parity across the three backends (mask shape/dtype, confidence scoring); graceful fallback when a backend's optional dependency is missing; unjustified duplication between backends that could share more via `_common.py`.

## Batch 6: Background Generation (GenAI) [DONE]

**Files:** `vlm_photo_editor/background/__init__.py`, `background/composite.py`, `background/generator.py`, `background/quality.py`, `background/AGENTS.md`, `background/providers/__init__.py`, `background/providers/base.py`, `background/providers/google_provider.py`, `background/providers/huggingface.py`, `background/providers/openai_provider.py`, `background/providers/replicate.py`

**Rationale:** The one place genAI is invoked, and the one place the "subject pixels frozen, only masked region changes" invariant and "keys reach only the provider client at call time" security rule both apply simultaneously across five provider integrations plus compositing.

**Review focus:** API-key handling in each provider client (never logged/persisted); composite.py correctly restricts edits to the mask region; seed/model/prompt recorded for reproducibility; duplicated request/retry logic across the five provider files that could be unified; quality.py's checks are meaningful vs. decorative.

## Batch 7: Secrets & Redaction [DONE]

**Files:** `vlm_photo_editor/secrets/__init__.py`, `secrets/redaction.py`, `secrets/store.py`, `secrets/AGENTS.md`

**Rationale:** Small, security-critical module implementing the env→keyring→`.env` resolution order and the log-redaction filter — the two mechanisms that back CLAUDE.md's "keys are secret" principle.

**Review focus:** redaction regex/pattern completeness (won't miss key formats); whether `RedactionProcessor` is actually wired into every log sink or just this module; store.py never writing keys to disk in plaintext.

## Batch 8: Config & Model Registry [DONE]

**Files:** `vlm_photo_editor/config/__init__.py`, `config/policy.py`, `config/registry.py`, `config/settings.py`, `vlm_photo_editor/models/__init__.py`, `models/registry.py`

**Rationale:** Cross-cutting configuration layer — policy.py presumably encodes the Auto/PS-strict/No-PS modes referenced throughout CLAUDE.md, while the two registries (config and model) manage available backends/models. Grouped because both are lookup/config tables read by many other modules.

**Review focus:** policy enum/values consistency with what ops/planner actually check; registry defaults are safe (no accidental Photoshop-required paths, honoring "Photoshop is optional, never required)"; settings.py secret/config separation.

## Batch 9: Pipeline Orchestration [DONE]

**Files:** `vlm_photo_editor/pipeline/__init__.py`, `pipeline/batch.py`, `pipeline/cost_router.py`, `pipeline/job_queue.py`, `pipeline/plan_cache.py`

**Rationale:** Batch-processing and job-scheduling layer sitting above the single-image planner/executor flow — cost_router and job_queue in particular are natural spots for concurrency and cost-estimation bugs.

**Review focus:** job_queue concurrency/race conditions; cost_router estimation correctness vs. actual provider pricing; plan_cache invalidation correctness (stale cached plans served after a source change); whether batch orchestration duplicates logic already in `agents/edit_flow.py`.

## Batch 10: Recipe & Preferences

**Files:** `vlm_photo_editor/recipe/__init__.py`, `recipe/renderer.py`, `recipe/session.py`, `recipe/store.py`, `vlm_photo_editor/preferences/__init__.py`, `preferences/store.py`

**Rationale:** Both modules persist state derived from completed edits — recipes (replayable edit history) and learned user preferences — and both are explicitly called out in CLAUDE.md as needing to be "viewable and editable," making them a natural persistence-layer pair to review together.

**Review focus:** recipe store never embeds API keys (model name only, per principle 2); recipe replay determinism; preference store data model doesn't silently override user's explicit choices; file/session storage error handling (corrupt recipe files, concurrent writes).

## Batch 11: Streamlit App / UI

**Files:** `vlm_photo_editor/app/__init__.py`, `app/main.py`, `app/state.py`, `app/stubs.py`, `app/AGENTS.md`, `app/components/__init__.py`, `app/components/batch_review.py`, `app/components/canvas.py`, `app/components/plan_view.py`, `app/components/prefs_panel.py`, `app/components/preview.py`, `app/components/settings.py`, `app/components/upload.py`

**Rationale:** The largest single-file component in the repo (`main.py`, 817 lines) plus its component tree — the human-in-the-loop approval surface where plan review, change requests, and settings/prefs all converge. Size alone (main.py is 2-5x any other file) suggests it's the most likely spot for maintainability issues and mixed concerns.

**Review focus:** approval loop genuinely blocks execution until explicit user approval (principle 4); change-request flow correctly regenerates plan rather than mutating step-IDs; masked API key display in settings.py; main.py's size/complexity — candidate for splitting into more components; UX flow for plan review, batch review, and error states.

## Batch 12: Tests

**Files:** `tests/__init__.py`, `tests/integration/__init__.py`, `tests/unit/__init__.py`, `tests/unit/test_background.py`, `test_edit_flow.py`, `test_framing.py`, `test_imageio.py`, `test_op_catalog.py`, `test_ops.py`, `test_p9_critic.py`, `test_p10_hardening.py`, `test_p11_batch.py`, `test_p13_character_focus.py`, `test_planner.py`, `test_prefs.py`, `test_recipe.py`, `test_schema.py`, `test_secrets.py`, plus `tests/fixtures/` (face_portrait.jpg, `prompts/base_prompt_full_mode.txt`, `schemas/sample_opgraph.json`, `schemas/sample_plan.json`, `schemas/sample_recipe.json`)

**Rationale:** `test_ops.py` (626 lines) and `test_planner.py` (656 lines) are the two largest test files, and several test files (`test_op_catalog.py`, `fixtures/prompts/`) are untracked/new alongside the schema changes in Batch 1 — worth checking whether new code has matching new coverage or whether tests still reflect the pre-change contract.

**Review focus:** per CLAUDE.md testing guidance, check for `for`-loops that should be `@pytest.mark.parametrize`, and narrow single-assertion tests that could merge; coverage gaps against Batches 1-3 (schema/ops changes); whether `slow`/`integration` markers are used correctly; fixture data realism.

## Batch 13: Project Tooling, Docs & Build Config

**Files:** `pyproject.toml`, `requirements.txt`, `requirements-anthropic.txt`, `requirements-huggingface.txt`, `requirements-llamacpp.txt`, `requirements-mediapipe.txt`, `requirements-ollama.txt`, `requirements-onnxruntime.txt`, `requirements-openai.txt`, `requirements_dev.txt`, `Dockerfile`, `.dockerignore`, `packages.txt`, `.env.example`, `.gitignore`, `README.md`, `RUNBOOK.md`, `CLAUDE.md`, `plans/photo_editor_build_plan.md`, `plans/future_improvements.md`, `plans/issues.md`, `agent_notes/*.md`, `agent_notes/generate_module_map.py`, `agent_notes/search_module_map.py`, `agent_notes/view_module_map.py`, `agent_notes/utility_scripts/cleanup.sh`, `agent_notes/utility_scripts/run_all_reviews.sh`, `.claude/commands/*.md`, `.claude/skills/*/SKILL.md`, `.claude/settings.json`, `.claude/settings.local.json`, `.vscode/settings.json`

**Rationale:** Everything that configures the build/dev environment or documents/automates the Claude Code workflow rather than the product itself — split into optional-dependency requirements files (per-provider), deployment config, and the agent-tooling layer (commands, skills, module-map scripts) that this very review depends on.

**Review focus:** the 8-way requirements-file split for redundancy/unjustified fragmentation vs. `pyproject.toml` extras; `.env.example` never contains a real secret; Dockerfile doesn't bake in credentials or run as root unnecessarily; `.claude/settings.local.json` being untracked (check it isn't meant to be gitignored-but-isn't, given it holds local permission overrides); module-map generation scripts' correctness since `codebase-navigation` skill depends on them being accurate.

## Excluded from Review

`.pytest_cache/`, `.ruff_cache/` (tool caches), `vlm_photo_editor.egg-info/` (generated build metadata), `.env` (real secret file — must never be opened/echoed), `.git/`.
