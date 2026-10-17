# Log

Chronological, append-only. One dated line per nontrivial change to the bundle or to project
conventions. Newest at the bottom.

---

- 2026-08-24 — Restructured CLAUDE.md: Done Gate, Testing, Git Commits, and Subagents moved to
  `done_gate.md`, `testing.md`, `git.md`, `subagents.md`, leaving 4-6 line stubs inline (trigger +
  prohibitions + link). Added `insights.md` and `log.md`. Fixed two factual errors in CLAUDE.md —
  pytest markers (`e2e` was missing; default run excludes e2e, not slow) and `.tmp_scripts/`, which
  was documented as scratch space but absent from `.gitignore` (now added). CLAUDE.md 267 → 227 lines.
- 2026-08-24 — Recorded that the Done Gate's `ruff` row is red on a clean tree (48 pre-existing
  errors, 1 auto-fixable). Baseline table + the interim passing condition are in `done_gate.md`.
- 2026-08-24 — `run_checks.sh` gained scoped-pytest flags (`[PATH ...]`, `-k`/`--match`,
  `-m`/`--marker`, `--ignore`, `--short [N]`); pytest moved off the shared `run()` path so `--short`
  can pipe to `tail` while keeping the real exit code via `PIPESTATUS[0]`. CLAUDE.md, `done_gate.md`,
  and `commands.md` updated to match; full flag list lives in `done_gate.md`, the other two point at it.
- 2026-08-24 — Added `utility_scripts/validate_okf.py`: checks bundle links resolve, `index.md` has a
  row per file (and no row without a file), and every backticked `agent_notes/…` path in CLAUDE.md
  exists. No frontmatter checks — this bundle deliberately has none, so the validator enforces that
  choice instead of the OKF spec. Standalone; not wired into `run_checks.sh` or `cleanup.sh`.
  Also fixed two CLAUDE.md drifts it now guards: the Done Gate's "every BLOCK row PASS" (unreachable
  while the ruff baseline is 48 errors) and the hand-copied "67/75 DoD checkboxes" (now a pointer).
- 2026-09-07 — Renamed the local inference-model dir `.test_models/` → `infer_models/` and
  nested the YOLO export under `infer_models/yolo/yolo26s.onnx`; it is now the app's bundled
  `yolo_onnx_model_path` default (was e2e-fixture-only). `.gitignore`, `commands.md`, e2e
  conftest/tests updated. Still gitignored (38 MB, Ultralytics AGPL).
- 2026-09-08 — `yolo_onnx` now requires a sibling `classes.txt` (0-based, human/person class)
  to be `ready`; it populates `DetectedSubject.label`. Added `infer_models/yolo/classes.txt`
  (COCO-80) committed via a `.gitignore` negation (`!infer_models/**/classes.txt`). New public
  `detection` API: `detector_labels()`, `detector_has_label()`, `requires_classes_txt()`.
  `FramingMode.FACE_ONLY` is hidden from the Composition dropdown / RECOMMEND_BEST menu unless
  the active Character Focus backend has a "face" label (carried on new
  `FramingIntent.face_framing_allowed`). Schema left permissive by design.
- 2026-08-24 — Fixed the `Stop` hook in `.claude/settings.json`: it pointed at
  `/media/tk/Programming1/…` (nonexistent — repo is `/media/tk/Programming/…`) and hid the failure
  behind `2>/dev/null`, so `cleanup.sh` had never run. Now `$CLAUDE_PROJECT_DIR`-relative, stderr
  visible. Evidence it was dead: `agent_ignore/module_map.json` was ten days stale.
  ~15 stale `Programming1` entries remain in `permissions.allow` — dead weight, not breakage.
- 2026-09-09 — Fixed B5, CFG-B1, S-C1, OPS-B2 from `plans/issues.md`. New bundle-relevant
  bits: (1) `OpSpec.optional_params` closes the op param contract — `ops/validator.py`
  rejects any `Op.params` key outside `required ∪ optional ∪ {invert, focus_*}` (S-C1 via
  the round-2 SC-S1 recommendation); documented in `schema/AGENTS.md`. (2) `cv_backend`
  16-bit inpaint/denoise now reconstruct with `* 257` (not `<< 8`) and log a warning;
  known-limitation note added to `ops/AGENTS.md`. (3) `app/tmp_layout.sweep_stale()` +
  once-per-session call from `state.init_state()` reaps orphaned scratch dirs (B5's
  session-end gap). (4) Cross-provider model swaps must use `ModelRegistry.set_entry()`,
  not `.set()` (CFG-B1) — docstring warning added.
- 2026-09-30 — Model presets bumped: Claude sonnet/opus 4.x → `claude-sonnet-5-5` / `claude-opus-5-5`;
  OpenAI gpt-5.6 luna/terra + gpt-4o/4o-mini → `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra` (each with
  a `(no reasoning)` twin). Default planner + critic now `gpt-6.1-sol` (needs `OPENAI_API_KEY`).
- 2026-10-01 — Character Focus now pluggable: `DetectorModel` + `detection/registry.py`
  (legacy settings slots + `infer_models/<dir>/` scan + user-added paths in
  `AppSettings.detectors_file`). Person/human-class requirement dropped (UI warns instead);
  target-class filter (`detect_subject(..., target_labels)`, default = all classes, so no
  result change for the bundled COCO model); yolo `model.json` layouts `yolov8|yolov5|nms`.
  `CharacterFocusBackend` and recipes untouched. See `detection/AGENTS.md`.
- 2026-10-02 — Planner-quality P1/P2 (plans/planner_quality_improvements.md): `rotate`/`denoise`
  keep dtype (cv2, bicubic); `white_balance` flipped to Lightroom direction (higher K = warmer);
  WB + `exposure` now linear-light (exposure has an extended-Reinhard highlight shoulder, alpha
  untouched). `Recipe.schema_version` added (2); `RecipeStore.load` mirrors v1 WB temperature
  (`13000 - T`, clamped). Plan-cache keys gained a `v2:` salt. Linear-light exposure is NOT
  migratable: v1 recipes replay with the new math. Prompt snapshot fixture regenerated.
- 2026-10-02 — New `analysis/` module + `schema/report.py` (`ImageReport`, `ExifSummary`):
  deterministic luma/clipping/cast/sharpness/noise/tilt/EXIF measurements, not yet wired into
  the planner (Phase 5 of plans/planner_quality_improvements.md).
- 2026-10-02 — Planner now takes `image_report` (MEASUREMENTS block in user message, rules in
  system prompt only when passed; `AppSettings.image_report_enabled` kill switch). `_encode_image`:
  no contrast stretch for uint16, <=1568 px long edge, ICC -> sRGB, original-coordinate-space
  note. Added `tests/eval/` (marker `eval`; synthetic cases, oracle + opt-in VLM tier).
- 2026-10-03 — Findings D/E/F of planner_quality_improvements.md: `planner/repair.py` (shared bounded
  compile+revise loop; `CompilerError.repairable`; batch now validates crops at plan time),
  `HumanPlan.diagnosis` + prompt (few-shot `EXAMPLE_PLANS`, op order, minimal-edit rules; plan-cache
  key v3; prompt snapshot regenerated), Critic v2 (`analysis/critic_checks.py` + `StepCheck`,
  explicit verdict, opt-in one-shot auto-revise), eval `already_fine` case + `compare.py`.
- 2026-10-05 — planner_quality_improvements.md follow-up: new `tone` op (catalog, PIL LUT, critic
  P95/P5 checks, prompt order/rules/example, eval `bright_sky`; plan-cache key v4; prompt snapshot
  regenerated), `savers` JPEG quality 95 / 4:4:4 + EXIF carried over (IO-D3 partial),
  `repair.check_plan_sanity` plan-time caps. Plan doc now carries a per-item status table.
- 2026-10-09 — new `saturation` and `sharpen` ops (catalog, PIL backend, prompt order/magnitudes/
  measurement rule, eval `flat_colour` + `soft`; plan-cache key v5; prompt snapshot regenerated).
- 2026-10-13 — eval harness: execute-time rejections (e.g. masked op with no bbox) share the repair budget
  (`_compile_and_dry_run`), `CaseResult.ops` records the executed plan, `already_fine` scene made genuinely
  neutral, `flat_colour` intent matched to its metric. `savers`: 16-bit TIFF now embeds ICC. VLM A/B (3 runs,
  fixed harness) = no net effect of MEASUREMENTS; see `plans/planner_quality_improvements.md` status table.
- 2026-10-16 — fixes: `Planner.revise` takes `original_intent`, adds REVISION RULE + plan-changed retry (`plans_equivalent`); Dismiss on learned prefs calls `remove_learned` and records `Preferences.dismissed` (aggregator skips them); batch viewer (`batch_review._render_viewer`) replaces review queue + collapsed expanders; Composition selector shared via `components/framing.py`.
- 2026-10-16 — batch: `batch_review.render_preview` (◀ ▶ Before/After at top of panel, uploads pre-run, bounded 1600px cache), Mode A single-image plan preview (`_do_batch_plan_preview`, blocked for genAI/PS/bbox plans), shared `components/character_focus.py` (targets survive panel switches).
- 2026-10-16 — batch Mode A no longer applies one identical plan: `Planner.adapt` + `pipeline.batch.adapt_plan_to_batch` re-plan each image from the approved plan (plan image verbatim; plans above the approved risk/backend envelope stay NEEDS_REVIEW). `apply_plan_to_batch` kept (shared `_compile_and_execute`).
- 2026-10-16 — bundle cleanup: removed `utility_scripts/run_all_reviews.sh` (its `plans/plan_review.md` is gone); pruned shipped entries from `future_improvements.md` (local face detection, structlog, Character Focus framing); `.claude/` is no longer tracked (ignored, stays on disk).
- 2026-10-17 — merged `agent_notes/future_improvements.md` into `plans/future_improvements.md`; dropped stale entries (precision-exploration options superseded by module map, op-catalog Extension Point A shipped); file removed from bundle.
