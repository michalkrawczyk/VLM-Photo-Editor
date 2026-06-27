## Overview

VLM Photo Editor: Streamlit app (~65 source files, ~17 test files) with a layered architecture — `schema/` at the root, then `secrets/` + `config/`, then `imageio/` + `ops/` + `planner/`, then `agents/` + `recipe/` + `preferences/` + `background/` + `pipeline/`, capped by `app/`. The strictest invariants are: originals never overwritten, API keys never logged/stored, every op validated before execution, plan step-IDs never mutated. Batches follow module-layer boundaries; security and data-integrity risks dominate the review priority.

---

## Batch 1: Schema Layer [DONE]

**Files:**
- `vlm_photo_editor/schema/__init__.py`
- `vlm_photo_editor/schema/ops.py`
- `vlm_photo_editor/schema/plan.py`
- `vlm_photo_editor/schema/prefs.py`
- `vlm_photo_editor/schema/recipe.py`
- `vlm_photo_editor/schema/batch.py`

**Rationale:** Root dependency imported by every other layer; contracts here propagate breakage everywhere. Schema correctness, completeness of discriminated unions, field constraints, and validator logic are the primary concerns. Any missing `model_validator` or loose `Any` type here weakens all downstream validation.

**Review focus:** Correctness of field validators and discriminated unions; missing required constraints (ranges, non-empty lists); `recipe.py` must not have any field that could hold a raw key; `batch.py` is new and may lack the same rigour as older schemas.

---

## Batch 2: Security & Configuration [DONE]

**Files:**
- `vlm_photo_editor/secrets/store.py`
- `vlm_photo_editor/secrets/redaction.py`
- `vlm_photo_editor/config/policy.py`
- `vlm_photo_editor/config/registry.py`
- `vlm_photo_editor/config/settings.py`
- `vlm_photo_editor/models/registry.py`

**Rationale:** These files form the security perimeter and policy enforcement boundary. `store.py` resolves keys (env → keyring → `.env`); `redaction.py` must scrub all log sinks; `policy.py` enforces PS-strict / Auto / No-PS op allowlists. A gap in any of these could leak credentials or allow unapproved ops to execute silently.

**Review focus:** Key leakage paths (logging, exception messages, repr); redaction pattern completeness; whether policy checks can be bypassed by op aliasing or missing entries in the registry; `registry.py` modified in current diff — check for regressions.

---

## Batch 3: Image I/O [DONE]

**Files:**
- `vlm_photo_editor/imageio/container.py`
- `vlm_photo_editor/imageio/loaders.py`
- `vlm_photo_editor/imageio/savers.py`

**Rationale:** Only layer that touches real disk. The non-negotiable invariant is that `savers.py` never writes to the source path. `loaders.py` handles both RAW (rawpy → 16-bit numpy) and standard formats; mixing them up corrupts data silently. Path sanitization happens here or nowhere.

**Review focus:** Source-overwrite guard in `savers.py`; correct rawpy → numpy → Pillow handoff (bit depth, channel order); path traversal or symlink risks; error paths that could silently drop data.

---

## Batch 4: Ops Execution [DONE]

**Files:**
- `vlm_photo_editor/ops/executor.py`
- `vlm_photo_editor/ops/mask.py`
- `vlm_photo_editor/ops/validator.py`
- `vlm_photo_editor/ops/backends/cv_backend.py`
- `vlm_photo_editor/ops/backends/pil_backend.py`
- `vlm_photo_editor/ops/backends/genai_backend.py`
- `vlm_photo_editor/ops/backends/stubs.py`

**Rationale:** Execution core — every edit runs through here. `executor.py` must validate against OpGraph before dispatching; `validator.py` is the gate. `genai_backend.py` must store model + prompt + seed in the recipe for every call. `mask.py` must guarantee subject pixels are never written by background ops.

**Review focus:** Validation bypass paths (ops that skip `validator.py`); missing seed capture in `genai_backend.py`; mask boundary correctness; backend dispatch errors that fall through silently; stub coverage gaps that hide missing real implementations.

---

## Batch 5: Planner & Templates [DONE]

**Files:**
- `vlm_photo_editor/planner/compiler.py`
- `vlm_photo_editor/templates/planner.py`
- `vlm_photo_editor/templates/framing.py`

**Rationale:** The compiler translates `HumanPlan` → `OpGraph`, linking compiled ops back to stable step-IDs. Templates inject user intent into the VLM prompt. Plan/executor parity (Principle 8) is enforced here: the compiler must reject ops not in the active policy. Step-ID mutation mid-session is a correctness bug.

**Review focus:** Step-ID stability across recompile; ops proposed outside active policy accepted without error; prompt injection surface in template string interpolation; compiler output not validated against `OpGraph` schema before use.

---

## Batch 6: Agents [DONE]

**Files:**
- `vlm_photo_editor/agents/planner.py`
- `vlm_photo_editor/agents/critic.py`
- `vlm_photo_editor/agents/edit_flow.py`
- `vlm_photo_editor/agents/aggregator.py`

**Rationale:** VLM integration layer using LangGraph. `planner.py` calls the model and returns a `HumanPlan`; `critic.py` verifies results; `edit_flow.py` orchestrates the human-in-the-loop approval loop; `aggregator.py` distills learned preferences. LLM output is untrusted and must be validated before any downstream use.

**Review focus:** LLM output parsed without schema validation; critic verdict that can be bypassed by `edit_flow.py` control flow; aggregator writing preferences without sanitization; exception handling that swallows model errors and silently proceeds.

---

## Batch 7: Recipe & Preferences [DONE]

**Files:**
- `vlm_photo_editor/recipe/session.py`
- `vlm_photo_editor/recipe/store.py`
- `vlm_photo_editor/recipe/renderer.py`
- `vlm_photo_editor/preferences/store.py`

**Rationale:** Persistence layer for non-destructive recipes and learned user preferences. `recipe/store.py` serialises ops to disk — any field that carries a raw key here is a security violation. `session.py` owns in-memory state; atomicity bugs here corrupt the replay chain. `preferences/store.py` is new and its write path may lack the same hardening.

**Review focus:** Recipe JSON fields that could embed API keys; session state mutation that breaks step-ID stability; non-atomic writes to preference store; renderer producing output that diverges from the stored op graph.

---

## Batch 8: Background Generation

**Files:**
- `vlm_photo_editor/background/generator.py`
- `vlm_photo_editor/background/composite.py`
- `vlm_photo_editor/background/quality.py`

**Rationale:** Only module allowed to call genAI for pixel content. `composite.py` applies the generated background while keeping subject pixels frozen (Principle 6). `generator.py` must record model + prompt + seed. `quality.py` gates acceptance — a broken gate lets bad outputs through silently.

**Review focus:** Subject pixel leakage through composite boundary; missing seed capture before generation call; quality threshold bypass or exception swallow; any path where the generated image replaces subject pixels.

---

## Batch 9: Pipeline / Batch

**Files:**
- `vlm_photo_editor/pipeline/batch.py`
- `vlm_photo_editor/pipeline/job_queue.py`
- `vlm_photo_editor/pipeline/cost_router.py`
- `vlm_photo_editor/pipeline/plan_cache.py`

**Rationale:** New module (current diff) handling multi-image batch processing. `job_queue.py` owns concurrency state; `cost_router.py` selects cheap vs. expensive model paths; `plan_cache.py` reuses compiled plans across images. All four are freshly written and lack the battle-testing of older modules.

**Review focus:** Queue state leaks between jobs (shared mutable state); plan cache returning stale plans after policy change; cost router using stale model cost data; batch failures that silently skip images rather than reporting errors.

---

## Batch 10: Streamlit UI

**Files:**
- `vlm_photo_editor/app/main.py`
- `vlm_photo_editor/app/state.py`
- `vlm_photo_editor/app/stubs.py`
- `vlm_photo_editor/app/components/upload.py`
- `vlm_photo_editor/app/components/canvas.py`
- `vlm_photo_editor/app/components/plan_view.py`
- `vlm_photo_editor/app/components/preview.py`
- `vlm_photo_editor/app/components/settings.py`
- `vlm_photo_editor/app/components/prefs_panel.py`
- `vlm_photo_editor/app/components/batch_review.py`

**Rationale:** Entry point and session-state boundary. `state.py` is the only authorised mutator of Streamlit session state; components that bypass it create race conditions on reruns. `settings.py` displays provider keys — masking must be correct. `main.py` enforces human-in-the-loop: approval button must gate execution, not just plan display. `settings.py` and `state.py` are in the current diff.

**Review focus:** Ops triggered before user approval (Principle 4 violation); API key displayed unmasked in `settings.py`; session state mutated outside `state.py`; `batch_review.py` (new) bypassing the normal approval flow; stubs left wired into production paths.

---

## Batch 11: Tests

**Files:**
- `tests/unit/test_schema.py`
- `tests/unit/test_secrets.py`
- `tests/unit/test_imageio.py`
- `tests/unit/test_ops.py`
- `tests/unit/test_planner.py`
- `tests/unit/test_recipe.py`
- `tests/unit/test_background.py`
- `tests/unit/test_framing.py`
- `tests/unit/test_prefs.py`
- `tests/unit/test_edit_flow.py`
- `tests/unit/test_p9_critic.py`
- `tests/unit/test_p10_hardening.py`
- `tests/unit/test_p11_batch.py`
- `tests/integration/__init__.py`

**Rationale:** Test suite covers the main pipeline but integration tests are empty. The newest tests (`test_p10_hardening.py`, `test_p11_batch.py`) are untracked, suggesting they were written before the implementation stabilised.

**Review focus:** `for` loops instead of `@pytest.mark.parametrize`; over-mocking that hides real contract drift (especially in security paths); missing tests for source-overwrite guard, key-in-recipe, and mask boundary; `tests/integration/` being empty when the whole pipeline integration is the riskiest surface.
