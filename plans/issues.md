# VLM Photo Editor — Bug & Issue Tracker

Audit date: 2026-06-16. All tests pass (122 passed, 2 skipped) but the issues below are either untested paths, design gaps, or principle violations.

---

## BUGS — cause crashes or incorrect behavior

### B2: Revision error causes infinite retry loop
**File:** [vlm_photo_editor/app/main.py:65-84](vlm_photo_editor/app/main.py#L65)

`_do_revise_plan` catches exceptions internally and sets `state["error"]` but does **not** clear `state["change_request"]`. Back in `main.py:421-425`:

```python
change = state.get("change_request") or ""
if change:
    _do_revise_plan(change)
    st.rerun()
```

After a failed revision, `change_request` is still set, `st.rerun()` fires, the revision is attempted again, fails again — infinite loop until the browser is closed.

Fix: add `state.set("change_request", "")` in the `except` block of `_do_revise_plan`.

---

### B5: Uploaded image temp file never deleted
**File:** [vlm_photo_editor/app/main.py:37-40](vlm_photo_editor/app/main.py#L37)

```python
with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
    tmp.write(file.getvalue())
```

`delete=False` and no cleanup path. Every upload leaks a temp file. Large RAWs (30–100 MB each) accumulate in `/tmp` until the OS sweeps them. Fix: track `tmp_path` in session state and delete on new upload or session end, or use `delete=True` + immediately call `load(tmp_path)` before the context manager exits.

---

### B7: Saved file and recipe written to `/tmp`
**File:** [vlm_photo_editor/app/main.py:128-136](vlm_photo_editor/app/main.py#L128)

```python
source = edited.source_path   # == temp file path e.g. /tmp/tmpXXXXXX.jpg
dest = source.parent / f"{source.stem}_edited{source.suffix}"
# → /tmp/tmpXXXXXX_edited.jpg
RecipeStore.save(recipe, directory=source.parent)
# → /tmp/tmpXXXXXX.edit.json
```

Output is siloed in the system temp directory, not beside the original upload. The `/tmp` path shown in the success banner confuses users and files may be deleted by OS cleanup.

Fix: determine an actual output directory (e.g., prompt user or use `~/Pictures/vlm_edits/`).

---

### B8: `Recipe.created_at` always empty
**File:** [vlm_photo_editor/app/main.py:135](vlm_photo_editor/app/main.py#L135) and [vlm_photo_editor/schema/recipe.py:22](vlm_photo_editor/schema/recipe.py#L22)

`Recipe(source_path=..., op_graph=...)` uses the default `created_at=""`. The field is never populated. Sidecar files have `"created_at": ""`, making them unsortable by date and harder to inspect.

Fix: default to `datetime.utcnow().isoformat()` in the schema, or populate at call site.

---

## DESIGN ISSUES — incomplete implementations or principle violations

### D1: `_execute` node in `edit_flow.py` is a stub
**File:** [vlm_photo_editor/agents/edit_flow.py:58-60](vlm_photo_editor/agents/edit_flow.py#L58)

```python
def _execute(state: EditState) -> dict:
    # Wired in P7.
    return {}
```

The LangGraph agent graph's execute node does nothing. Even if the graph were hooked up to the UI (see B6), edits would never apply. P7 marked the DoD "User can upload → see plan → edit/accept → preview before/after → save" as complete, but the graph itself isn't wired.

---

### D4: `composite` subject-pixel invariant uses `assert` (disabled with `-O`)
**File:** [vlm_photo_editor/background/composite.py:130-134](vlm_photo_editor/background/composite.py#L130)

The DoD invariant "subject pixels are unchanged" is enforced with:

```python
assert np.all(result.pixels[safe_outside] == source.pixels[safe_outside]), ...
```

`assert` is compiled away under `python -O`. This is the most critical safety check in the pipeline and must use an explicit `if not …: raise` instead.

---

### D5: Instruct-model branch in generator is identical to inpaint branch
**File:** [vlm_photo_editor/background/generator.py:110-114](vlm_photo_editor/background/generator.py#L110)

```python
if instruct:
    inp["image"] = io.BytesIO(image_bytes)
else:
    inp["image"] = io.BytesIO(image_bytes)
    inp["mask"] = io.BytesIO(mask_bytes)
```

Both branches set `inp["image"]` identically. The only difference is the mask. Instruction-based edit models typically require a text-only or image+instruction payload, not the same key. This is likely a copy-paste error; the instruct branch should be verified against the actual model API.

---

### D6: `edit_graph` module-level singleton creates a LangGraph on import
**File:** [vlm_photo_editor/agents/edit_flow.py:107](vlm_photo_editor/agents/edit_flow.py#L107)

```python
edit_graph = build_edit_graph()
```

`InMemorySaver` is instantiated at module import time. If this module is imported in a multi-worker Streamlit deployment, each worker gets its own in-memory checkpointer and sessions can't be shared or persisted. The singleton should be removed; callers should construct the graph explicitly.

---

### D7: `seam_metric` threshold in `quality.py` is 10× the `AppSettings` threshold
**File:** [vlm_photo_editor/background/quality.py:47](vlm_photo_editor/background/quality.py#L47) and [vlm_photo_editor/config/settings.py:9](vlm_photo_editor/config/settings.py#L9)

`AppSettings.seam_quality_threshold = 0.15` (plausible for a 0–1 normalized gradient metric). But `run_background_pipeline` passes `threshold=10.0` (hardcoded), and `select_best` uses `threshold: float = 10.0` as its default. The `AppSettings` value is never read by the pipeline. The threshold controlling how often results are flagged for manual review is effectively unconfigured.

---

## MISSING TESTS

### T2: No test for revision error path in UI (uncovers B2)

### T3: No test that `AcceptMode.AUTO` skips human approval in the UI flow (uncovers B6)

### T4: No regression test for crop out-of-bounds validation

### T5: `test_raw_16bit` always skipped — no RAW fixture in repo
**File:** [tests/unit/test_imageio.py:83-88](tests/unit/test_imageio.py#L83)

The only test verifying 16-bit RAW handling is permanently skipped because the fixture file doesn't exist. This means the entire RAW codepath is untested in CI.

---

## DESIGN ISSUES (continued)

### D13: FRAME op planner–executor coordination undefined

The planner proposes `frame` ops with a `mode` string (e.g. `rule_of_thirds`). The PIL backend (`pil_backend._frame`) currently applies only a geometric center crop to a mode-appropriate aspect ratio — no subject detection. This stop-gap prevents crashes but does not satisfy the P5 framing spec.

Design work needed:
- Define how the planner conveys composition intent to a subject-aware backend (e.g. providing face bounding boxes from a detection pre-pass so the crop centers on the subject).
- Decide whether the planner receives saliency/face data as input context before generating frame ops, or whether the executor handles it transparently behind the `FRAME` op interface.
- Route `FRAME` through the P5 framing module once that module is complete, replacing the PIL backend center-crop stub.

---

### D14: Composition mode sends only target aspect ratio — no focus instruction

**File:** framing module / wherever `FRAME` op parameters are constructed for the planner.

Each composition mode (Face Only, Rule of Thirds, Head & Shoulders, etc.) currently passes only the target frame ratio to the planner and executor. It provides no instruction about *what region to prioritize*, so the executor falls back to a geometric center crop that ignores subject position.

Examples of the missing signal:
- **Face Only** — crop tightly around the face bounding box; do not include the torso.
- **Head & Shoulders** — include head + upper chest; exclude legs.
- **Rule of Thirds** — place the primary subject's eye-line on the upper third; do not simply center.
- **Full Body** — ensure feet and top of head are both within frame.

Fix: augment the `FRAME` op payload (or a parallel `FramingIntent` schema) with a short natural-language focus instruction per mode, generated at mode-selection time. The planner can include this in its reasoning; the executor uses it to bias the crop anchor toward the correct subject region (face bbox, eye-line, centroid, etc.) rather than the image center.

This is a prerequisite for D13's subject-aware backend design: the executor needs to know *which* subject region to protect before it can request the right detection pre-pass.

---

### D15: Save path UX undefined — no dialog, no structured tmp layout

**Related:** B7 (saved file written to `/tmp`), B5 (temp file never deleted).

Two separate concerns:

**1. User-defined output path (save-as dialog)**
After hitting the Save button, the user should be able to choose where the edited file goes via a native file-save dialog. Streamlit has no built-in file picker; options:
- `tkinter.filedialog.asksaveasfilename` — works in local deployments, fails in browser-based ones.
- Offer a download button (`st.download_button`) as the universal fallback; the browser handles the destination.
- For a desktop packaging path, wrap with a native dialog via `tkinter` or `pyside6.QFileDialog`, guarded by a capability flag.

Default suggested: `st.download_button` first (works everywhere); add native dialog behind a `USE_NATIVE_DIALOG=1` env flag for local installs.

**2. Structured tmp directory for per-image data**
Current code scatters all temp files flat in `/tmp`. Required layout:

```
/tmp/vlm_photo_editor/
└── <image-stem>_<session-id>/   ← one subfolder per uploaded image
    ├── original.<ext>
    ├── edited.<ext>
    └── <stem>.edit.json
```

- Create `vlm_photo_editor/` on first use; create the per-image subfolder on upload.
- Sweep the per-image subfolder on new upload or session end (fixes B5).
- The subfolder name should be deterministic within a session so the recipe and output always land together.

---

## Batch 1 Review — Schema Layer

Review date: 2026-06-26. Files: `schema/__init__.py`, `schema/ops.py`, `schema/plan.py`, `schema/prefs.py`, `schema/recipe.py`, `schema/batch.py`.

---

### Bugs & Correctness

**S-B1: `HumanStep.op_names` / `op_params` parallel lists lack parity validator**
**File:** [vlm_photo_editor/schema/plan.py:16-17](vlm_photo_editor/schema/plan.py#L16)

`op_names` and `op_params` are independent lists with no `model_validator` enforcing equal length. Mismatched lengths pass schema validation but cause `IndexError` in the compiler.

Fix: add `@model_validator(mode="after")` asserting `len(self.op_names) == len(self.op_params)`.

---

**S-B2: `AcceptMode`, `FramingIntent`, `EditDelta` missing from `schema/__init__.py`**
**File:** [vlm_photo_editor/schema/__init__.py](vlm_photo_editor/schema/__init__.py)

All three are actively used across 10+ call sites but are absent from both the `from .ops import …` / `from .prefs import …` lines and `__all__`. Every caller imports directly from the submodule (`schema.ops`, `schema.prefs`). If the submodule is reorganised the callsites break without a schema-layer signal.

Fix: add all three to the imports and `__all__` in `__init__.py`.

---

### Security & Data Integrity

**S-D1: `BatchImageRecord.filename` is unvalidated — path traversal risk**
**File:** [vlm_photo_editor/schema/batch.py:27](vlm_photo_editor/schema/batch.py#L27)

The comment states the field is "used for display and save destination". There is no stripping of `..`, leading `/`, or null bytes. If `filename` is used as `Path(output_dir) / record.filename`, an adversarial upload name can escape the output directory.

Fix: add `@field_validator("filename")` that calls `Path(v).name` (basename only, strips directory components) and rejects names containing null bytes.

---

**S-D2: `GenAIOp.prompt` and `GenAIOp.model` accept empty strings**
**File:** [vlm_photo_editor/schema/recipe.py:11-14](vlm_photo_editor/schema/recipe.py#L11)

A `GenAIOp` with a blank prompt or model name passes validation but creates a non-reproducible recipe entry, violating Principle 5 (deterministic and reproducible).

Fix: `prompt: str = Field(min_length=1)`, `model: str = Field(min_length=1)`.

---

**S-D3: `Recipe.source_path` is an unvalidated bare string**
**File:** [vlm_photo_editor/schema/recipe.py:20](vlm_photo_editor/schema/recipe.py#L20)

`source_path` is serialised to the sidecar JSON. An attacker-controlled recipe can embed a path to a critical file; any replay logic that opens `recipe.source_path` directly would follow it.

Fix: validate on construction (`Path(v).resolve()` and check it's within an allowed root), or type as `pathlib.Path` so callers are at least aware they're dealing with a path.

---

### Code Smells / Maintainability

**S-C1: `Op.params: dict[str, Any]` — complete type erasure**
**File:** [vlm_photo_editor/schema/ops.py:67](vlm_photo_editor/schema/ops.py#L67)

Every `OpName` has a specific parameter contract (`crop` needs `left/top/right/bottom`; `rotate` needs `angle`; etc.), but `params` accepts any dict. No per-op discriminated union exists. Validation is deferred entirely to the executor, making the schema useless as a correctness gate.

This is the single largest schema weakness: a mistyped param key (`"angl"` instead of `"angle"`) passes schema validation, passes compilation, and only fails at executor dispatch.

Fix (incremental): define a `CropParams`, `RotateParams`, etc. `TypedDict` or `BaseModel` per op and add a `model_validator` that parses `params` against the correct model when `op_name` is known.

---

**S-C2: `HumanStep.op_names: list[str]` instead of `list[OpName]`**
**File:** [vlm_photo_editor/schema/plan.py:16](vlm_photo_editor/schema/plan.py#L16)

Bare `str` bypasses the `OpName` enum. An invalid op name (e.g. `"crpp"`) passes schema validation but fails at compiler time with a confusing error.

Fix: `op_names: list[OpName] = Field(default_factory=list)`.

---

**S-C3: `HumanPlan.mode` and `EditDelta.mode` are unvalidated bare strings**
**Files:** [vlm_photo_editor/schema/plan.py:23](vlm_photo_editor/schema/plan.py#L23), [vlm_photo_editor/schema/prefs.py:35](vlm_photo_editor/schema/prefs.py#L35)

`HumanPlan.mode: str = "full"` and `EditDelta.mode: str` accept any string. An edit mode enum should exist per Principle 7 (contracts before behavior), since the compiler and aggregator branch on this value.

---

**S-C4: `HumanPlan.chosen_framing_mode: str | None` should be `FramingMode | None`**
**File:** [vlm_photo_editor/schema/plan.py:24](vlm_photo_editor/schema/plan.py#L24)

`FramingMode` already exists in `ops.py`. Using `str | None` here means an invalid framing mode stored in a `HumanPlan` won't be caught until a downstream consumer tries to match it against the enum.

---

**S-C5: `Preferences.version` uses UUID — wrong semantics**
**File:** [vlm_photo_editor/schema/prefs.py:24](vlm_photo_editor/schema/prefs.py#L24)

`version: str = Field(default_factory=lambda: str(uuid.uuid4()))` generates a new random UUID on every construction. UUIDs convey no ordering and no schema compatibility, making it impossible to detect stale preference files or apply migrations.

Fix: use an integer counter (default `0`, incremented on each write) or an ISO timestamp; document what "version" means for this type.

---

**S-C6: `BatchImageRecord` uses `Any` for runtime types to avoid circular imports**
**File:** [vlm_photo_editor/schema/batch.py:25-29](vlm_photo_editor/schema/batch.py#L25)

`container: Any`, `edited_container: Any`, `plan: Any`, `op_graph: Any` erase all type information. The comments state what these fields "should be". The standard pattern for this situation is a `TYPE_CHECKING` guard with string-quoted forward refs; `arbitrary_types_allowed` is only necessary for non-Pydantic types (e.g. numpy arrays).

---

**S-C7: `HumanStep.index` has no non-negative constraint**
**File:** [vlm_photo_editor/schema/plan.py:13](vlm_photo_editor/schema/plan.py#L13)

`index: int` accepts `-1`, which would pass validation but break any step ordering logic.

Fix: `index: int = Field(ge=0)`.

---

### Performance

No significant issues at the schema layer (pure data classes, no hot paths).

---

### Over-engineered / Unjustified Functionality

**S-O1: `Recipe.branch` field has no documented purpose**
**File:** [vlm_photo_editor/schema/recipe.py:23](vlm_photo_editor/schema/recipe.py#L23)

`branch: str = "main"` is hardcoded to `"main"` everywhere and never populated with actual git branch info. If intended for reproducibility, it should be populated at recipe-creation time; if not, it adds noise to every saved sidecar.

Fix: remove the field or populate it from `subprocess.check_output(["git", "branch", "--show-current"])` at save time (guarded for non-git environments).

---

## Summary

All issues sorted by priority.

| # | Severity | File | Issue |
|---|----------|------|-------|
| B2 | High | main.py:65 | Revision error leaves `change_request` set → infinite retry loop |
| D1 | High | edit_flow.py:58 | `_execute` node is a stub; edits never apply |
| D4 | High | composite.py:130 | Subject-pixel invariant uses `assert` (disabled with `-O`) |
| D5 | High | generator.py:110 | Instruct-model branch identical to inpaint branch (copy-paste) |
| S-B1 | High | plan.py:16 | `op_names`/`op_params` parallel lists lack parity validator |
| S-D1 | High | batch.py:27 | `filename` unvalidated — path traversal risk |
| B5 | Medium | main.py:37 | Uploaded image temp file never deleted |
| B7 | Medium | main.py:128 | Saved file and recipe written to `/tmp` |
| D6 | Medium | edit_flow.py:107 | Module-level `edit_graph` singleton breaks multi-worker deploy |
| D7 | Medium | quality.py:47 | `seam_metric` threshold 10× `AppSettings` default; setting never read |
| D13 | Medium | — | FRAME op planner–executor coordination undefined |
| D14 | Medium | — | Composition mode sends only aspect ratio; no focus instruction |
| D15 | Medium | — | Save path UX undefined; no native dialog or structured tmp layout |
| T5 | Medium | test_imageio.py:83 | `test_raw_16bit` permanently skipped; RAW codepath untested |
| S-B2 | Medium | schema/__init__.py | `AcceptMode`, `FramingIntent`, `EditDelta` missing from `__all__` |
| S-C1 | Medium | ops.py:67 | `Op.params: dict[str, Any]` — type erasure, no per-op validation |
| S-D2 | Medium | recipe.py:11 | `GenAIOp.prompt`/`model` accept empty strings |
| S-D3 | Medium | recipe.py:20 | `source_path` unvalidated bare string — replay path risk |
| B8 | Low | main.py:135 | `Recipe.created_at` always empty |
| S-C2 | Low | plan.py:16 | `op_names: list[str]` instead of `list[OpName]` |
| S-C3 | Low | plan.py:23 | `HumanPlan.mode` and `EditDelta.mode` unvalidated bare strings |
| S-C4 | Low | plan.py:24 | `chosen_framing_mode: str \| None` instead of `FramingMode \| None` |
| S-C5 | Low | prefs.py:24 | `Preferences.version` uses UUID — no ordering or migration semantics |
| S-C6 | Low | batch.py:25 | `BatchImageRecord` runtime types erased to `Any` |
| S-C7 | Low | plan.py:13 | `HumanStep.index` accepts negative values |
| S-O1 | Low | recipe.py:23 | `Recipe.branch` hardcoded `"main"`, never populated from git |
| T2 | Low | — | No test for revision error path (uncovers B2) |
| T3 | Low | — | No test that `AcceptMode.AUTO` skips approval (uncovers B6) |
| T4 | Low | — | No regression test for crop out-of-bounds validation |

---

## Batch 2 Review — Security & Configuration

Review date: 2026-06-26. Files: `secrets/store.py`, `secrets/redaction.py`, `config/policy.py`, `config/registry.py`, `config/settings.py`, `models/registry.py`.

---

### Bugs & Correctness

**SEC-B1: Anthropic API keys are never redacted**
**File:** [vlm_photo_editor/secrets/redaction.py:6](vlm_photo_editor/secrets/redaction.py#L6)

```python
_KEY_PATTERN = re.compile(r"(?:sk-|r8_)[A-Za-z0-9]{20,}")
```

Anthropic keys have the format `sk-ant-api03-[alphanumeric-and-dashes]`. After matching the `sk-` prefix, the next chars are `ant-` — the hyphen is not in `[A-Za-z0-9]`, so the match stops at `ant` (3 chars < 20) and the whole match fails. Replicate (`r8_`) and OpenAI plain (`sk-[alphanumeric]`) keys are redacted; Anthropic keys are not. Since Anthropic is the primary provider, this is the most critical gap.

Fix: broaden the pattern to cover hyphens in the key body:
```python
_KEY_PATTERN = re.compile(r"(?:sk-ant-|sk-|r8_)[A-Za-z0-9\-]{20,}")
```
Or use a generic high-entropy token pattern as a secondary pass.

---

**SEC-B2: `record.args = ()` breaks log formatting when `msg` has `%` placeholders**
**File:** [vlm_photo_editor/secrets/redaction.py:11-12](vlm_photo_editor/secrets/redaction.py#L11)

```python
record.msg = _KEY_PATTERN.sub("[REDACTED]", str(record.msg))
record.args = ()
```

If a logger is called with `logger.info("key=%s value=%s", key, val)`, `record.msg` is `"key=%s value=%s"` and `record.args` is `(key, val)`. Clearing `args` to `()` before the `Formatter` calls `msg % args` causes a `TypeError` (too few args). The `[REDACTED]` substitution also runs on the unformatted template, not the rendered string.

Fix: format first, then redact:
```python
record.msg = _KEY_PATTERN.sub("[REDACTED]", record.getMessage())
record.args = ()
```

---

**SEC-B3: `PolicyMode` and `_OP_SETS` are completely disconnected**
**File:** [vlm_photo_editor/config/policy.py](vlm_photo_editor/config/policy.py)

`PolicyMode` defines values `"auto"`, `"ps_strict"`, `"no_ps"`. `_OP_SETS` has keys `"full"`, `"background"`, `"frame"`. `allowed_ops_for_mode(PolicyMode.AUTO)` raises `KeyError("Unknown edit mode: 'auto'")`. There is no function that maps a `PolicyMode` to an allowed op set. Principle 8 (Planner ↔ Executor parity) has no enforcement mechanism.

Fix: add entries to `_OP_SETS` for each `PolicyMode` value — e.g. `"auto": set(OpName)`, `"ps_strict": {ops that have a PS backend}`, `"no_ps": {ops that don't require PS}` — and change the parameter type to `PolicyMode`.

---

**SEC-B4: `build_client` ignores `entry.provider`; routes by model name string**
**File:** [vlm_photo_editor/models/registry.py:59-79](vlm_photo_editor/models/registry.py#L59)

```python
if "claude" in model_id or "anthropic" in model_id:
    ...
if "gpt" in model_id:
    ...
```

`entry.provider` is defined on `ModelEntry` but never consulted for non-local providers. A `ModelEntry("future-anthropic-model-v2", provider="anthropic")` where "claude" doesn't appear in the ID falls through to `raise ValueError`. Conversely, any model with "claude" in a custom name routes to Anthropic regardless of the configured provider.

Fix: branch on `entry.provider` first, fall back to string heuristic only when provider is unset.

---

**SEC-B5: `ModelRegistry.set()` silently drops `vllm_base_url`, `gguf_path`, `max_images_per_call`**
**File:** [vlm_photo_editor/config/registry.py:78-85](vlm_photo_editor/config/registry.py#L78)

```python
self._entries[role] = ModelEntry(
    model, existing.provider, existing.hf_repo, existing.loader
)
```

`vllm_base_url`, `gguf_path`, and `max_images_per_call` are silently reset to defaults. A vLLM entry with a non-default `base_url` loses it on the first `set()` call.

Fix: use `dataclasses.replace(existing, model_id=model)`.

---

### Security & Data-Integrity Risks

**SEC-D1: `DebugSettings.vlm_prompt_debug = True` by default**
**File:** [vlm_photo_editor/config/settings.py:32](vlm_photo_editor/config/settings.py#L32)

VLM prompts may contain file paths, personal photo descriptions, and other user-supplied context. With debug mode enabled by default, this content is logged in every deployment. A user who never touches settings ships with prompt logging active.

Fix: default to `False`; enable explicitly in dev.

---

**SEC-D2: Module-level singletons shared across Streamlit sessions**
**Files:** [vlm_photo_editor/config/registry.py:95](vlm_photo_editor/config/registry.py#L95), [vlm_photo_editor/config/settings.py:22](vlm_photo_editor/config/settings.py#L22), [vlm_photo_editor/config/settings.py:34](vlm_photo_editor/config/settings.py#L34)

`_registry`, `_settings`, and `_debug` are module-level objects. In a Streamlit multi-session process (one process, multiple threads), a call to `registry.set("planner", "new-model")` in one session mutates the object for all sessions. A user changing their preferred model in one browser tab affects all concurrent users.

Fix: store these in `st.session_state` rather than at module level, or make `get_registry()` / `get_settings()` session-aware.

---

**SEC-D3: API key passed as keyword arg — traceback leakage risk**
**File:** [vlm_photo_editor/models/registry.py:67](vlm_photo_editor/models/registry.py#L67)

```python
return ChatAnthropic(model=model_id, api_key=api_key)
```

If `ChatAnthropic.__init__` raises (e.g., network error during validation), Python may include kwargs in the traceback or exception repr, exposing the raw key. Structlog's redaction filter runs on log output, not on exception repr.

Fix: wrap the constructor call in a try/except, log only the sanitized error message, and re-raise without the original exception chain (`raise ... from None`) or with a sanitized message.

---

### Code Smells / Maintainability

**SEC-C1: `logger` defined but never used in `store.py`**
**File:** [vlm_photo_editor/secrets/store.py:6](vlm_photo_editor/secrets/store.py#L6)

Dead import and name. Remove to avoid confusion about whether secret operations are being logged.

---

**SEC-C2: `mask()` reveals 80 % of a 5-character key**
**File:** [vlm_photo_editor/secrets/store.py:57-60](vlm_photo_editor/secrets/store.py#L57)

`mask("ABCDE")` → `"*BCDE"`. The guard `if len(key) <= 4` does not protect 5-char keys. In practice, real API keys are longer, but if the function is ever called on a short token it gives a false sense of masking.

Fix: `if len(key) <= 8: return "****"` (or similar minimum hiding threshold).

---

**SEC-C3: `_entries` accessed as public attribute from outside**
**File:** [vlm_photo_editor/models/registry.py:95](vlm_photo_editor/models/registry.py#L95)

```python
for entry in registry._entries.values():
```

The underscore-prefix convention signals private. The `ModelRegistry` class should expose an `entries()` method returning an appropriate view.

---

**SEC-C4: Redaction filter not guaranteed to run before first log call**

`install_redaction_filter()` must be called at application startup. Nothing enforces that it is called before any log output. If a module logs at import time (before `main.py` starts), those records skip redaction.

Fix: call `install_redaction_filter()` at the top of `secrets/redaction.py` itself (module-level side effect), or document clearly that it must be the very first call in `app/main.py`.

---

### Performance

**SEC-P1: `_vllm_reachable()` makes HTTP requests on every call, no caching**
**File:** [vlm_photo_editor/models/registry.py:90-110](vlm_photo_editor/models/registry.py#L90)

`available_loaders()` calls `_vllm_reachable()`, which does two HTTP probes with a 1-second timeout each. If `available_loaders()` is called on every Streamlit UI refresh (e.g., in `settings.py` to populate a dropdown), this adds up to 2 s of blocking I/O per rerender.

Fix: cache the result with `functools.lru_cache(maxsize=1)` and a TTL, or run the probe once at startup.

---

### Over-engineered / Unjustified Functionality

**SEC-O1: `install_loader_deps()` runs pip at runtime**
**File:** [vlm_photo_editor/models/registry.py:129-137](vlm_photo_editor/models/registry.py#L129)

Installing packages from within a running app is fragile (pip may upgrade transitive deps, break the running process, require write access to site-packages). This is a setup-time concern, not a runtime one.

Fix: remove `install_loader_deps()` from this module; provide a `scripts/install_loader.sh` or document the pip command in README. If a UI button must trigger it, limit its scope to a clearly labeled "Developer" section and warn the user about the restart requirement.

---

### Summary — Batch 2 additions

| # | Severity | File | Issue |
|---|----------|------|-------|
| SEC-B1 | Critical | redaction.py:6 | Anthropic API keys (`sk-ant-*`) not redacted — pattern misses hyphens in key body |
| SEC-B3 | High | policy.py | `PolicyMode` and `_OP_SETS` disconnected — `allowed_ops_for_mode("auto")` raises `KeyError` |
| SEC-B4 | High | models/registry.py:59 | `build_client` ignores `entry.provider`; routes by model name string match |
| SEC-D1 | High | settings.py:32 | `vlm_prompt_debug = True` by default — VLM prompts logged in production |
| SEC-B2 | Medium | redaction.py:11 | `record.args = ()` before format — `TypeError` on `%`-style log calls |
| SEC-B5 | Medium | config/registry.py:78 | `ModelRegistry.set()` silently drops `vllm_base_url`, `gguf_path`, `max_images_per_call` |
| SEC-D2 | Medium | registry.py:95, settings.py:22 | Module-level singletons mutated across Streamlit sessions |
| SEC-D3 | Medium | models/registry.py:67 | API key in constructor kwarg — exposed in exception repr/traceback |
| SEC-C4 | Medium | redaction.py | `install_redaction_filter()` not auto-called; logs before startup skip redaction |
| SEC-P1 | Low | models/registry.py:90 | `_vllm_reachable()` makes HTTP probes on every call, no cache |
| SEC-C1 | Low | secrets/store.py:6 | `logger` defined but never used |
| SEC-C2 | Low | secrets/store.py:57 | `mask()` reveals 80% of 5-char key |
| SEC-C3 | Low | models/registry.py:95 | `_entries` accessed as public attribute from outside |
| SEC-O1 | Low | models/registry.py:129 | `install_loader_deps()` runs pip at runtime — setup concern, not runtime |
