# Code Review Plan

Scope: entire `vlm_photo_editor/` source tree + matching test files.
Strategy: ordered by data-flow layer (schema → infra → execution → pipeline → UI) so bugs that cross layers are caught when both sides are fresh in context.
Known issues from `plans/issues.md`: B2, B5, B7, B8, D1, D4–D7, D13–D15, T2–T5. Each batch notes which it should surface.

---

## Batch 1 — Schema & Contracts

**Files:**
- `vlm_photo_editor/schema/ops.py`
- `vlm_photo_editor/schema/plan.py`
- `vlm_photo_editor/schema/recipe.py`
- `vlm_photo_editor/schema/prefs.py`
- `tests/unit/test_schema.py`

**Why first:** Schema is the root dependency — imports nothing from siblings, everything imports from it. Bugs here (wrong defaults, missing validators, loose types) propagate everywhere.

**Focus:**
- B8: `Recipe.created_at=""` — should default to `datetime.utcnow().isoformat()` in the schema
- `GenAIOp`: verify key field is absent; model name only
- `BoundingBox` validators: zero-dimension and negative-origin guards — are they complete?
- `OpGraph`: no ordering or step-ID uniqueness validator — silent duplicates possible
- `FramingIntent`: does it carry enough signal (focus instruction, bbox) for D13/D14, or just aspect ratio?
- `CompilerResult.plan` linkage: `Op.step_id` → `HumanStep.id` — is the back-reference enforced at schema level?
- `Preferences.learned`: confidence field bounds validator — present in test, present in schema?

---

## Batch 2 — Secrets, Config & Model Registry

**Files:**
- `vlm_photo_editor/secrets/store.py`
- `vlm_photo_editor/secrets/redaction.py`
- `vlm_photo_editor/config/settings.py`
- `vlm_photo_editor/config/policy.py`
- `vlm_photo_editor/config/registry.py`
- `vlm_photo_editor/models/registry.py`
- `tests/unit/test_secrets.py`

**Why together:** Security + configuration primitives. `SecretStore`, `RedactionFilter`, `ModelRegistry`, and `AppSettings` are tightly coupled. D7 lives here.

**Focus:**
- D7: `AppSettings.seam_quality_threshold=0.15` defined but never consumed — `run_background_pipeline` hardcodes `threshold=10.0`; dead config field
- `RedactionFilter`: does it cover structlog async handlers, not just the root logger?
- `ModelRegistry.set`/`set_entry`: thread-safety under multi-worker Streamlit deploys
- `get_settings()` singleton: risk of stale config after env var mutation in tests — is it reset between test runs?
- `build_client` in `models/registry.py`: key must be resolved at call-time from `SecretStore`, not cached on construction
- `allowed_ops_for_mode`: if a new `PolicyMode` is added, does it raise or silently return empty set?

---

## Batch 3 — ImageIO

**Files:**
- `vlm_photo_editor/imageio/container.py`
- `vlm_photo_editor/imageio/loaders.py`
- `vlm_photo_editor/imageio/savers.py`
- `tests/unit/test_imageio.py`

**Why isolated:** "Originals are sacred" is principle 1. The overwrite guard and the RAW 16-bit pipeline both live here. T5 means the entire RAW codepath is untested in CI.

**Focus:**
- T5: `test_raw_16bit` permanently skipped — no fixture; entire `_load_raw` path is a blind spot
- `savers.save`: overwrite guard — is it checked before the output file is opened (not after)?
- `_load_pil`: EXIF orientation rotation — handled transparently or silently ignored?
- `ImageContainer.copy()`: deep-copy of numpy array — verify no shared-buffer aliasing
- Import boundary: `loaders.py` must never import from `ops/` or `agents/`

---

## Batch 4 — Ops: Validator, Executor & Backends

**Files:**
- `vlm_photo_editor/ops/validator.py`
- `vlm_photo_editor/ops/executor.py`
- `vlm_photo_editor/ops/mask.py`
- `vlm_photo_editor/ops/backends/pil_backend.py`
- `vlm_photo_editor/ops/backends/cv_backend.py`
- `vlm_photo_editor/ops/backends/genai_backend.py`
- `vlm_photo_editor/ops/backends/stubs.py`
- `tests/unit/test_ops.py`

**Why together:** Validator → Executor → Backend is a single contract chain. A bug in dispatch or validation directly corrupts pixels or silently skips ops.

**Focus:**
- D5 (adjacent): `genai_backend` or `cv_backend` instruct-model branch sets `inp["image"]` identically in both branches — likely wrong API payload
- `Executor._resolve_backend`: unknown backend string — raises or falls back to stub silently?
- `pil_backend._frame`: center-crop stub — flag as not satisfying P5 spec (D13)
- `mask.bbox_to_mask`: edge case when bbox equals image bounds exactly — off-by-one?
- `validate_op_graph`: validates individual ops but not ordering or step-ID uniqueness
- T4: no regression test for crop out-of-bounds validation

---

## Batch 5 — Planner: Compiler, Templates & Planner Agent

**Files:**
- `vlm_photo_editor/planner/compiler.py`
- `vlm_photo_editor/templates/planner.py`
- `vlm_photo_editor/templates/framing.py`
- `vlm_photo_editor/agents/planner.py`
- `tests/unit/test_planner.py`
- `tests/unit/test_framing.py`

**Why together:** Prompt construction → VLM → `HumanPlan` → `OpGraph` is one pipeline. Template precision directly affects compiler correctness; framing intent must flow end-to-end.

**Focus:**
- D13/D14: `focus_instruction` exists in `templates/framing.py` — does it actually reach the compiled `FRAME` op params, or stop at the prompt?
- Compiler step-ID linkage: `HumanStep.id` → `Op.step_id` — verify IDs are never silently rewritten mid-session
- `_ps_available()` called inside `Compiler.compile` — should this be injected to avoid hidden I/O in the compiler?
- `Planner._encode_image`: does it always produce a model-compatible payload for all bit depths?
- `build_system_prompt`: does `_prefs_lines(None)` produce empty string gracefully?
- Principle 8 (planner↔executor parity): compiler must reject ops not in `allowed_ops_for_mode` for the active policy

---

## Batch 6 — Background Pipeline

**Files:**
- `vlm_photo_editor/background/generator.py`
- `vlm_photo_editor/background/composite.py`
- `vlm_photo_editor/background/quality.py`
- `vlm_photo_editor/background/__init__.py`
- `tests/unit/test_background.py`

**Why separate:** Three distinct known bugs all live here. Subject-pixel invariant is the hardest safety guarantee in the system.

**Focus:**
- D4: `assert` in `composite.py` for subject-pixel invariant — must be `if not …: raise RuntimeError` (disabled under `python -O`)
- D5: `generator.py` instruct-model branch — both branches set `inp["image"]` identically; mask omitted from instruct path
- D7: `run_background_pipeline` passes hardcoded `threshold=10.0`; `AppSettings.seam_quality_threshold` is never read
- `color_match`/`grain_match`: are subject-pixel constraints also using `assert`?
- `select_best`: handles `candidates=[]` without `IndexError`?
- `Generator._get_client`: key fetched from `SecretStore` at call-time, not cached on `__init__`?

---

## Batch 7 — Recipe & Session

**Files:**
- `vlm_photo_editor/recipe/store.py`
- `vlm_photo_editor/recipe/renderer.py`
- `vlm_photo_editor/recipe/session.py`
- `tests/unit/test_recipe.py`

**Why together:** Persistence, replay, and undo/redo form a single correctness surface. A bug here silently corrupts the non-destructive editing guarantee.

**Focus:**
- B8 call-site: `Recipe(source_path=..., op_graph=...)` in `app/main.py` never sets `created_at` — schema default should fix this
- `RecipeStore.save`: does it enforce output path ≠ source path, or is that only in `savers.py`?
- `Renderer._inject_seeds`: are seeds reproducible across Python versions?
- `UndoStack.push` after undo: verify future states are discarded (not just the pointer moved), and mutations to peeked state can't leak back
- XMP stubs raise — documented clearly enough that callers don't silently swallow?

---

## Batch 8 — Preferences

**Files:**
- `vlm_photo_editor/preferences/store.py`
- `vlm_photo_editor/agents/aggregator.py`
- `tests/unit/test_prefs.py`

**Why together:** `PreferenceStore`, `DeltaStore`, and `Aggregator` form a single feedback loop that influences VLM prompts. `preferences/` is a newer module not yet in `structure.md` — higher risk of undocumented invariants.

**Focus:**
- `add_learned`: dedup logic — equality on `text` field only, or full object?
- `toggle_rule`: handles rule present in both `explicit` and `learned` lists?
- `Aggregator.aggregate`: fail-open on bad JSON — does it log the malformed payload before discarding?
- `DeltaStore.clear`: atomicity — file truncated vs rewritten; risk of data loss on partial write
- `approve_learned`: promotes to explicit or just flips flag? Clarify data flow and whether the original learned entry is removed
- Threshold constant — consistent with test fixture expectations?

---

## Batch 9 — Agents & Edit Flow

**Files:**
- `vlm_photo_editor/agents/edit_flow.py`
- `vlm_photo_editor/agents/critic.py`
- `tests/unit/test_edit_flow.py`
- `tests/unit/test_p9_critic.py`

**Why together:** LangGraph orchestration and critic operate at the same agent layer. D1 and D6 both live in `edit_flow.py`.

**Focus:**
- D1: `_execute` returns `{}` — edit graph is completely non-functional end-to-end despite unit tests passing
- D6: `edit_graph = build_edit_graph()` at module import — `InMemorySaver` singleton dangerous in multi-worker deploys
- `_can_auto_approve`: is the `RiskTier` comparison exhaustive? A new tier value could silently bypass human review
- `Critic.verify`: `_encode_image` called for before and after images — verify no re-encoding artifact changes the comparison
- T2: no test for revision error path that would uncover B2
- T3: no test that `AcceptMode.AUTO` skips human approval

---

## Batch 10 — App UI & State

**Files:**
- `vlm_photo_editor/app/main.py`
- `vlm_photo_editor/app/state.py`
- `vlm_photo_editor/app/stubs.py`
- `vlm_photo_editor/app/components/upload.py`
- `vlm_photo_editor/app/components/preview.py`
- `vlm_photo_editor/app/components/plan_view.py`
- `vlm_photo_editor/app/components/canvas.py`
- `vlm_photo_editor/app/components/prefs_panel.py`
- `vlm_photo_editor/app/components/settings.py`

**Why last:** App is the integration point — calls every other module. All upstream contracts are understood by this point. Highest concentration of known bugs.

**Focus:**
- B2: `_do_revise_plan` except block does not clear `change_request` → `st.rerun()` infinite loop
- B5: `NamedTemporaryFile(delete=False)` with no cleanup path leaks large RAW files in `/tmp`
- B7: save output path derived from temp file path → edited file and recipe land in `/tmp`
- B8 call-site: `Recipe(...)` construction never sets `created_at`
- D15: no structured tmp layout; no save-path dialog or download button
- `state.py log_intent`: wired to structlog with `RedactionProcessor` active?
- `settings.py _ps_available()` vs `planner/compiler.py _ps_available()`: two independent implementations — risk of divergence
- `prefs_panel.py`: calls `PreferenceStore.save()` after mutations, or only on explicit user action?
- Accept-mode toggle: all three modes (`MANUAL`, `AUTO`, `FULL_AUTO`) covered in the UI path?
