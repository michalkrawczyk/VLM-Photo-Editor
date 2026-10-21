# Insights

Observations and conclusions from agent sessions that could improve future runs. Not task status,
not a restatement of a diff, not anything readable from code. One entry per durable fact.

---

## CLAUDE.md drifts from the bundle; the bundle is usually right

Discovered 2026-08-24. CLAUDE.md's Testing section claimed two pytest markers and "default run
excludes `slow`". `pyproject.toml` defines three (`slow`, `integration`, `e2e`) and its `addopts`
excludes **e2e**. `commands.md` had it correct the whole time — the inline copy in CLAUDE.md had
drifted from the file it was summarizing.

**Apply:** when CLAUDE.md and an `agent_notes/` file disagree on a verifiable fact, check the source
(`pyproject.toml`, the script) and fix CLAUDE.md. Duplicating a fact inline is what caused the
drift — prefer a pointer over a copy for anything that can change.

---

## A gitignore entry is not implied by a convention

Discovered 2026-08-24. CLAUDE.md instructed session scripts into `.tmp_scripts/` for a long time, but
that path was never added to `.gitignore` — only `agent_ignore/` was. Scratch files would have shown
up in `git status` and could have been committed.

**Apply:** any instruction that says "put throwaway output at path X" needs a matching `.gitignore`
line written at the same time. Check before trusting a documented scratch path.

---

## The Done Gate cannot go green today

Discovered 2026-08-24. `run_checks.sh` reports `ruff FAIL` on an unmodified tree — 48 errors, only 1
auto-fixable (mostly `E501` in prompt strings and deliberate `E402` lazy imports in Streamlit
modules). CLAUDE.md's T1 rule says "every BLOCK row PASS", which is unreachable.

**Apply:** a red `ruff` row after your change is not automatically your fault. Stash and re-run to
compare against the baseline before debugging. Baseline table and the interim passing condition
(no new errors in files your diff touched) are in [done_gate.md](done_gate.md). Cleaning the
baseline would make the gate honest again — worth doing as its own commit.

---

## mypy config is dead

`pyproject.toml` has `[tool.mypy] strict = true`, but mypy is not in `requirements_dev.txt`, not in
`.venv`, and no script runs it. `run_checks.sh` deliberately excludes it.

**Apply:** don't cite the strict-mypy config as evidence the codebase typechecks. It has never been
run clean. Typecheck status is unverified. Also see [commands.md](commands.md).

---

## The `edit_flow` LangGraph is not wired into the app

Discovered 2026-09-07. `agents/edit_flow.py::build_edit_graph` (and the module-level `edit_graph`)
looks like the orchestration spine but nothing runs it except `tests/unit/test_edit_flow.py`. The
real single-image flow is `app/main.py` (`_do_generate_plan` → `_do_revise_plan` → `_do_execute` →
`_do_save`) calling `Planner`/`Compiler`/`Executor` directly; `pipeline/batch.py` does its own.
Only `_can_auto_approve` is shared from `edit_flow`.

**Apply:** integration tests for the single-image path should drive the components the way
`app/main.py` does — including the drawn-region bbox injection at `app/main.py:284-294`, which the
graph's `_execute` node does NOT do (so a bare `background_replace` op fails the executor's
`require_bbox` check). `tests/integration/test_p8_5_mvp_gate.py` follows this.

---

## OpenAI reasoning models (gpt-6-luna / gpt-6.1-sol / gpt-6-astra) need a special planner path

Discovered 2026-09-07. Two independent walls between `ChatOpenAI` and the Planner's
`with_structured_output(HumanPlan)`:

1. Strict `json_schema` (langchain-openai's default) rejects `HumanPlan` — `HumanStep.op_params`
   is `list[dict[str, Any]]`, and strict mode demands `additionalProperties: false` everywhere.
2. `method="function_calling"` then 400s on **reasoning** models over `/v1/chat/completions`
   (`Function tools with reasoning_effort are not supported ... use /v1/responses or set
   reasoning_effort to 'none'`).

Working combos (both verified via e2e `test_full_edit_flow`):
- non-reasoning: `ModelEntry(reasoning_effort="none")` + `method="function_calling"`
- reasoning: `ModelEntry(use_responses_api=True)` + `method="function_calling"`

`ModelEntry` carries `reasoning_effort` / `use_responses_api` (OpenAI-only; ignored elsewhere).
`build_client` passes them through; `Planner.__init__` picks `method="function_calling"` iff
`provider == "openai"`. Critic/Aggregator are unaffected — they use plain `invoke()` + regex.

**Apply:** any new OpenAI reasoning model added to `PLANNER_PRESETS` needs `use_responses_api=True`
(or a `(no reasoning)` twin with `reasoning_effort="none"`), else plan generation 400s.

---

## HumanStep.step_id now normalises non-canonical UUIDs

Discovered 2026-09-07. GPT-5.6 emits `step_id` as bare 32-hex (no dashes); the old
`_UUID_RE` regex required the dashed 8-4-4-4-12 form and rejected it. `_require_uuid_format`
now does `str(uuid.UUID(str(v)))` — accepts dashed / 32-hex / `urn:uuid:` / braces, stores the
canonical dashed form. Still rejects real garbage (`"s1"`, `"step-001"`, malformed). Compiler
copies `step_id` straight through, so linkage stays byte-comparable.

**Apply:** don't reintroduce a format regex for step_id; `uuid.UUID()` is the validator.

---

## `.env` model paths resolve via `dotenv_values`, never `load_dotenv`

Discovered 2026-09-07. `config/settings.py::_path_setting` reads `<NAME>_MODEL_PATH` from
`os.environ`, then from `.env` via `dotenv_values()` — deliberately *not* `load_dotenv()`,
which would push the API keys in the same `.env` into `os.environ` where `subprocess.run`
calls (`install_backend_deps`, model-loader pip installs, the mediapipe probe) inherit them.
Same pattern as `secrets/store.py`. `yolo_onnx_model_path` additionally falls back to the
bundled, gitignored `infer_models/yolo/yolo26s.onnx` (renamed from `.test_models/`).

**Apply:** never add a blanket `load_dotenv()` at startup; extend `_path_setting` instead.
The main-flow Character Focus picker offers `detection.ready_backends()` (package + path),
not `available_backends()` (package only).

---

## `yolo_onnx` needs a sibling `classes.txt`; `face_only` is gated on a "face" label

Discovered 2026-09-08. `yolo_onnx` reads `classes.txt` from the model file's *directory*
(`_common.load_class_labels`, 0-based line index == class id). It must name a `human`/`person`
class (case-insensitive) or `ready_backends()` drops the backend and `detect()` raises — same
"no silent fallback" contract as a missing model path. `detect()` also raises on a class-count
mismatch vs the model's output. The bundled COCO-80 `infer_models/yolo/classes.txt` is now
committed via a `.gitignore` negation (`!infer_models/**/classes.txt`); the `.onnx` stays ignored.

`FramingMode.FACE_ONLY` is offered in the Composition dropdown and the planner RECOMMEND_BEST
menu **only** when `detection.detector_has_label(active_cf_backend, "face")` — carried to the
template on `FramingIntent.face_framing_allowed` (default `True`). The static schema
(`op_catalog` `enum_params`, `ops/validator.py`) stays permissive: a cached/hand-edited
`frame.mode == "face_only"` still validates and replays (degrades to `portrait_headroom`
geometry — both are a 3:4 centred/centroid crop). mediapipe returns `None` from
`detector_labels()` (labels embedded in the tflite, not introspected), so `face_only` is
hidden under mediapipe too.

**Apply:** don't move the `face_only` gate into schema validation — it must not depend on
`detection`/Streamlit state. Gate at the presentation layer only.

---

## `plans/issues.md` drifts from code — verify each ID before planning a fix

Discovered 2026-09-09. Planning fixes for B5, CFG-B1, S-C1, OPS-B2: the Summary
table line numbers were all stale, and two items were already partly fixed with no
status marker. B5's single-image temp leak was closed by `app/tmp_layout.py` (commit
b22c6d8, which also deleted the D15/B7/CFG-B2 detail sections but left their Summary
rows). CFG-B1's planner dropdown already moved to `set_entry`; only the generic-role
branch still had the bug. Round-2 batch reviews also supersede round-1 fixes (SC-S1's
`optional_params` explicitly replaces S-C1's per-op Pydantic-model suggestion).

**Apply:** treat the Summary table as an index, not truth. For each ID, open the cited
file at current `HEAD`, grep for the described construct, and check later batch
sections for a superseding fix, before writing any plan.

## Op semantics are versioned through `Recipe.schema_version` (2026-10-02)

**Gotcha:** sidecars (`*.edit.json`) persist op params but not op meaning. Any change to what
an op *does* (WB direction, exposure math) silently changes every saved recipe's output.
**Apply:** bump `RECIPE_SCHEMA_VERSION` (`schema/recipe.py`), add a pure migration in
`recipe/store.py::_migrate_recipe_dict` where the change is invertible, and bump
`plan_cache._KEY_VERSION` if the planner-facing wording changed. Pixel-precision-only
changes (e.g. rotate resampler) need no bump. Also: `test_op_catalog.py` pins the system
prompt byte-for-byte, so any `doc_lines` edit means regenerating
`tests/fixtures/prompts/base_prompt_full_mode.txt` (review the diff).

## Env: `.venv/bin/{pytest,black,isort,ruff}` shebangs are dead (2026-10-02)

They point at a moved path (`/media/tk/Programming/...`), so `run_checks.sh` reports FAIL for
black/isort/pytest on this box. Use `.venv/bin/python -m pytest|ruff|black|isort` instead.

## Planner input bug fixed: 16-bit images were contrast-stretched (2026-10-02)

`Planner._encode_image` used to min/max-stretch any non-uint8 frame to 0-255, so a dark or
flat 16-bit/RAW image reached the VLM looking correctly exposed. Now a plain `>> 8`. If a
planner ever "sees nothing to fix" on a RAW, check what bytes the model was actually sent.

## Critic expectations come from ops, not prose (2026-10-03)

`analysis/critic_checks.py` derives "what should have changed" from the compiled ops (net EV sign,
WB direction, denoise, levelling rotate). A model-written `expected_effects` field was rejected on
purpose: a model can emit "luma up" for any step, which would make the check vacuous. Also:
`tests/unit/test_batch_processing.py::test_concurrent_planning_wall_time` fails when run alone
(cold lazy imports inside the timed region, reproduced at HEAD); it passes after other test files
warm the imports.

## Copying source EXIF verbatim leaks the unedited thumbnail (2026-10-05)

Camera EXIF carries an IFD1 JPEG thumbnail. Passing `info["exif"]` bytes straight to `img.save`
keeps it, so file browsers show the *pre-edit* picture for an edited export. Rebuild through
`Image.Exif().load(raw).tobytes()` (drops IFD1, keeps the Exif/GPS sub-IFDs) — see
`imageio/savers._exif_bytes`. Orientation is already stripped by `ImageOps.exif_transpose` on load.

## 16-bit TIFF input loads as 8-bit (2026-10-13)

`loaders._load_pil` goes through Pillow, which cannot decode 16-bit-per-channel RGB TIFF: a uint16
RGB `.tif` comes back as uint8 / `bit_depth 8` (verified). Only RAW produces 16-bit containers, so
a 16-bit TIFF source is silently downgraded before any edit. Not fixed (out of scope of the
planner-quality work); a `tifffile` read path in `_load_pil` would fix it. Also: the 16-bit save
branch used to drop `icc_profile`; it now passes `iccprofile=` (tifffile cannot write EXIF IFDs).

2026-10-16 — `streamlit.testing.AppTest.from_file("vlm_photo_editor/app/main.py")` resolves relative to the *test file* on streamlit 1.65, so the 11 AppTest cases in `test_p13_character_focus.py` fail from a clean checkout (pre-existing). Run them with a temporary symlink `tests/unit/vlm_photo_editor -> ../../vlm_photo_editor` (remove after). Also `test_concurrent_planning_wall_time` fails alone on this machine (0.57s vs 0.45s budget) but passes inside the full run — timing-sensitive.

2026-10-19 — Gotchas from the S-D3/OE-B1/BG-*/SR-P1/IO-* fixes. (1) rawpy 0.27 has no EXIF or ICC accessor (the old IO-D2 text citing `color_desc`/`libraw_processed_image` was wrong): `_load_raw` tags the sRGB postprocess output with an sRGB ICC and lifts EXIF from the embedded JPEG preview (`extract_thumb`). (2) Pillow 12 already closes the fp inside `Image.load()`, so IO-D1's fd leak did not reproduce; the `with` is defensive. (3) `seam_metric` is a 0–~0.1 metric on [0,1] pixels and cannot separate good from bad cleanly (benign max 0.021, bad 0.002–0.106 in the sample); default `seam_threshold` is 0.03, `VLM_SEAM_THRESHOLD` overrides. (4) `Logger.handle()` checks only the filters of the logger a record went through — redaction hooks the record factory + a structlog processor instead.
