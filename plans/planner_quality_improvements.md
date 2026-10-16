# Plan: make VLM edit plans better + more professional

## Status (2026-10-05)

Findings below are the original 2026-10 review; this table is current.

| Item | Status |
|---|---|
| T0.1 WB direction | Done — Lightroom convention, linear light, documented in `OpSpec.doc_lines`. Tint not added. |
| T0.2 rotate/denoise 16-bit | Done — cv2 bicubic, native dtype, `crop_to_inscribed`; PIL denoise honours `strength`. |
| T0.3 / T1-E eval | Skeleton done — 9 synthetic oracle cases + opt-in VLM A/B (`EVAL_VLM=1`). VLM A/B (2026-10-13, gpt-6.1-sol, 11 synthetic cases): run 1 on the original harness showed baseline 10/11 vs with_report 8/11, but that was largely harness artefacts (masked tone op unexecutable without a bbox; `already_fine` scene had a built-in cast). After fixing (execute-time errors share the repair budget, neutral `already_fine`, `flat_colour` intent) 3 runs gave mean 10.33 (baseline) vs 10.00 (with_report): no net effect. Per case: `soft` 1/3 -> 3/3 with report; `flat_colour` 3/3 -> 0/3 (report-driven white_balance to the suggested temperature washes out the saturation gain); rest equal. Planner picked `saturation` and `sharpen` in every relevant run. **Open:** no real-photo set. |
| T1-A Image Report | Done (`analysis/`, `schema/report.py`, MEASUREMENTS block). |
| T1-B input hygiene | Done (1568 px, ICC→sRGB). Normalised crop coords **deferred** (T3, recipes). Histogram overlay dropped. |
| T1-C prompt | Done (diagnosis, order, magnitudes, few-shot, minimal-edit). |
| T1-D repair | Done (`planner/repair.py`). |
| T1-F sanity guard | Done — `repair.check_plan_sanity` (net \|ev\| ≤ 4, rotate ≤ 20° off a right angle). Always on, plan-time only. Crop-area cap dropped (tight crops are legitimate). |
| T2.1 `tone` | Done. Display-referred curve, not linear light (slider convention, PS-Curves expressible). |
| T2.2 saturation/vibrance | Done (2026-10-09) — `saturation` op `{saturation, vibrance}` −100..100, display-referred chroma scale about luma; eval `flat_colour`. Per-hue HSL not added. |
| T2.3 sharpen | Done (2026-10-09) — `sharpen` op `{amount, radius, threshold}`, luma-only unsharp mask; prompt says skip when noisy; eval `soft`. |
| T2.4 straighten | Covered by report `tilt_deg` → `rotate(-tilt, crop_to_inscribed)`; no new op. |
| T2.5 exposure linear + shoulder | Done. |
| T2.6 vignette/dehaze/graduated | Open, low priority. |
| T3-G diagnosis | Done. `expected_effect` rejected — critic derives expectations from ops (see `insights.md`). |
| T3-H Critic v2 | Done as two-stage in `app/main.py`; `edit_flow` graph not updated (it is not what the app runs). |
| T3-I proxy preview | **Open.** |
| T3-J richer prefs | **Open** — `EditDelta` unchanged. |
| T3-K output polish | JPEG quality 95 / 4:4:4 + EXIF carried over (IO-D3 partial). 16-bit TIFF: ICC now carried (2026-10-13); EXIF **deferred** (no source data, tifffile can't write the Exif IFD — see `future_improvements.md`). XMP/IPTC open. |

## Context

Planner today = one VLM call: JPEG of image + dims + intent (+ optional subject bbox, prefs) → `HumanPlan` → compiler → executor. Critic = separate, post-hoc, yes/no. Reviewed: `templates/planner.py`, `agents/planner.py`, `agents/critic.py`, `agents/edit_flow.py`, `planner/compiler.py`, `schema/op_catalog.py`, `ops/backends/{pil,cv}_backend.py`, `ops/executor.py`, `agents/aggregator.py`, `schema/prefs.py`.
Not read / unverified: `imageio/savers.py`, `background/`, `pipeline/plan_cache.py`, app UI. No code run. Impact estimates below are judgment, not measured.

Core diagnosis: planner guesses numbers from vibes, has a thin toolbox, has no feedback signal, and nothing measures whether changes helped. Four gaps: **data in**, **ops available**, **op quality**, **verification/learning**.

---

## Findings (evidence → consequence)

### A. Planner gets no measured data
- `_user_content` sends: JPEG q85 (full-res, no downscale, no colour-space conversion) + `WxH` + intent (`agents/planner.py:126-167`). Nothing else.
- `ImageContainer.metadata` = PIL `img.info` only; EXIF (ISO, WB, exposure, lens, focal) never reaches the prompt.
- Consequence: `ev`, `temperature`, `angle`, crop ints are guessed. Bounds are loose (`ev ±10`, `temp 1000–20000`) so a wild guess validates. VLMs are weak at pixel-precise grounding (already noted in `future_improvements.md`).

### B. Toolbox too thin for "professional" edits
- Global ops: crop, rotate, white_balance, exposure, denoise, frame. Local: mask + blur/fill/inpaint/background_replace.
- Prompt tells the VLM to write titles like "Open up shadows", "Recover highlights" (`templates/planner.py:70-71`). **No op can do that** — exposure is one global multiply. Planner↔Executor parity (principle 8) broken in spirit.
- Missing basics: contrast, highlights/shadows, whites/blacks, saturation/vibrance, sharpen, local dodge/burn (masked exposure exists but nothing drives it), vignette, auto-straighten.

### C. Existing ops are below professional quality
| Op | Issue (file) |
|---|---|
| `white_balance` | **Direction likely inverted vs photographer intuition.** Lower K → `r_mult>1` = warmer (`pil_backend.py:80-93`); Lightroom-style "Temp" goes the other way. Prompt says only "float 1000–20000 K" — no direction, no neutral point (6500 hard-coded). VLM has ~coin-flip. Also ignores tint, works in gamma space, JPEG-agnostic. **Verify first.** |
| `exposure` | Multiplies gamma-encoded sRGB by `2**ev` (`:96-103`), not linear light → hue/sat shift, hard clip, no highlight roll-off. |
| `rotate` | PIL `rotate(expand=True)` default NEAREST resample (jaggies), black corners, no inscribed-crop; `_from_pil` forces `bit_depth=8` → **16-bit silently downgraded** (`:74-77`, `:42-50`). |
| `denoise` | Default backend PIL = 3×3 median, ignores `strength` (`:106-109`); cv backend fine but 8-bit only. |
| `frame` | Pure aspect-ratio crop; subject-aware only if detector on. |

### D. Plan schema has no reasoning or testable expectation
- `HumanStep` = title/why/op_names/op_params. No scene diagnosis, no "expected measurable effect", no confidence. Critic therefore has nothing concrete to check.
- Prompt has no few-shot examples, no photographic op-order guidance (geometry → WB → tone → local → denoise → sharpen). Compiler doesn't lint order.
- `op_params` is free-form `dict` → model emits typo'd/out-of-range keys; only crop-bounds errors get an auto-repair retry (`edit_flow.py:114-123`). Other `CompilerError`s surface straight to the user.
- Crop asks for raw original-space pixel ints; if image is ever downscaled for the VLM these break. Normalised 0–1 coords are more robust.

### E. Critic is weak and isolated
- Sees only before/after/intent (not plan, ops, or numbers); "When in doubt, pass"; parse/API errors → pass (`critic.py`).
- Fail → `_do_critic_check` dumps user back to `plan_ready` with an error string (`app/main.py:359-372`). No auto-revise. Not a node in `edit_flow` graph.
- Matters most in `full_auto`, which has no human gate.

### F. No evaluation → can't tell if any change helped
- One fixture image (`tests/fixtures/face_portrait.jpg`), one prompt snapshot. No eval set, no metrics, no regression run for prompt/model changes. "Better" is currently unverifiable.

### G. Preference learning is shallow
- `EditDelta` = intent + change-request text + op *names* (`schema/prefs.py`). No param values, no user's manual corrections, no scene context, no rejects. Aggregator can only learn prose like "user likes warm tones", never "+0.3 EV, −400 K on backlit portraits".

---

## Recommendations (ranked: impact ÷ cost)

### Tier 0 — verify / fix before building (small, mostly T2)
1. **WB direction + prompt semantics.** Write a test: `temperature=4000` → is output warmer or cooler? Decide convention (recommend: match Lightroom; or switch to relative `temp_shift`/`tint` in [-100,100] since source K is unknown), document in `OpSpec.doc_lines`.
2. **`rotate`/`denoise` 16-bit + resample.** Use BICUBIC/LANCZOS; keep dtype; optional `crop_to_inscribed`.
3. **Eval harness skeleton** (see Tier 1-E) — do *before* prompt tuning so gains are measurable.

### Tier 1 — highest leverage, deterministic ("boring path")
A. **Image Report** (new `vlm_photo_editor/analysis/`, pure numpy/cv2; `ImageReport` pydantic in `schema/`, mirrors `DetectedSubject` pattern — computed by app/pipeline, passed into `Planner`, so `agents/` still doesn't import `imageio`/`ops`). Contents: luma percentiles/mean, clipped-shadow/highlight %, per-channel means + gray-world cast estimate, saturation mean, sharpness (Laplacian var), noise estimate, horizon/tilt angle (Hough), dominant subject/brightness split (reuse `detection/`), EXIF subset (ISO, WB mode, exposure comp). Injected as a `MEASUREMENTS:` block in the system prompt. Also shrinks op-param guessing: "highlights clipped 4.2% → don't raise exposure".
B. **VLM input hygiene.** Downscale to ~1568 px long edge, convert to sRGB via embedded ICC, cap payload; send normalised coords or scale factor; optionally send a second "histogram + thirds-grid overlay" image.
C. **Prompt upgrade** (`templates/planner.py`): realistic ranges ("typical ev −1…+1.5"), tighten `PARAM_BOUNDS` practical limits (soft clamp + warn), canonical op order, 2–3 few-shot plans per genre (portrait/landscape/product), "prefer minimal edits; do nothing if fine", define directions for every signed param.
D. **Generalised bounded auto-repair.** Reuse crop-retry pattern: any `CompilerError`/validation error → `revise` with error text, ≤2 retries, then surface. Shown as a revised plan (respects principle 3 "never silently rewritten": revision is visible + logged; in manual mode user still approves).
E. **Eval harness** (`tests/eval/`, marker `slow`/new `eval`): 30–50 images tagged (underexposed, backlit, cool/warm cast, tilted horizon, high-ISO, portrait/landscape/product) + intent. Pass criteria = deterministic metric deltas from A (clipping not worse, cast reduced, horizon error < 1°, subject pixels unchanged for bg edits, plan uses only allowed ops, no compile error). Track: pass-rate, #steps, cost, latency per prompt/model version. Optional external refs: MIT-Adobe FiveK (5 expert retouches/image — **check licence**) and an aesthetic predictor as a *noisy* secondary signal only.
F. **Post-compile sanity guard** (deterministic, cheap): cumulative |EV|, total WB shift, crop area lost, rotation size caps unless user intent asks; order lint. Essential for `full_auto`.

### Tier 2 — new/better ops (T3: schema + catalog; all via existing `register_op` — one place)
Add only the ones that make the prompt's own promises true, in this order:
1. `tone` : `{shadows, highlights, whites, blacks, contrast}` (curve-based, linear-light).
2. `saturation` / `vibrance` (+ optional per-hue HSL later).
3. `sharpen` (unsharp mask / Richardson-Lucy-lite, with radius/amount/threshold; after denoise).
4. `straighten` — planner says *intent*, executor uses measured tilt from Image Report (deterministic angle, not VLM-guessed).
5. Rework `exposure` to operate in linear light with soft highlight shoulder.
6. Later: vignette/dehaze, graduated/radial masked adjustments driven by detection.
Each needs: `OpSpec` (bounds, enum params, `ps_expressible`), backend impl, validator tests, prompt doc. Keep PS-strict parity.

### Tier 3 — structure, verification, learning
G. **Plan schema additions** (T3): `HumanPlan.diagnosis: str` (what's wrong, in photographer terms), `HumanStep.expected_effect` (measurable, e.g. "shadows P10 up", "cast toward neutral"). Planner fills diagnosis first (cheap "think then act"; avoids a second VLM call). Only escalate to a true two-stage (scene-analysis call → plan call) if eval shows single-call diagnosis is insufficient. Note P4 title says "two-stage" but code is one-shot.
H. **Critic v2.** Stage 1 deterministic: recompute Image Report on result, compare to each step's `expected_effect`, check subject-pixel invariance, clipping, halo/edge artifacts, SSIM outside edit region. Stage 2 VLM: gets plan + before/after stats + rubric (intent fidelity, naturalness, artifacts, composition; 0–5 each) and must cite which step is at fault. Remove "when in doubt, pass" bias → return `uncertain` explicitly. Move into `edit_flow` as a node; fail → bounded `revise` with critic reason (max 1 retry; genAI cost ceiling respected).
I. **Proxy preview.** Run plan on ≤2048 px proxy for fast revise loops; full-res only on approve. Show before/after + histogram in plan view; numeric sliders for editable params.
J. **Richer prefs.** Extend `EditDelta`: final param values (incl. user edits), image-report summary/scene tag, accepted/rejected. Derive *numeric priors* deterministically (median EV/K offset per scene tag) and inject as "user typically…" lines; keep LLM aggregator for prose style only. Named, versioned "Looks" (inspectable, editable).
K. **Output polish check** (unverified): confirm `savers.py` preserves EXIF + ICC, sane JPEG quality/subsampling, 16-bit TIFF path.

---

## Weak points / challenge
1. **Weakest: assuming Image Report numbers improve plans.** VLM may over-anchor or ignore them. → wasted prompt tokens, false confidence. *Alternative:* build eval (E) first, A/B with and without report.
2. **Op sprawl.** Each op multiplies failure modes, tests, PS-parity work, and planner confusion. → *Alternative:* add `tone` + `saturation` + `sharpen` only, then measure.
3. **Critic loop cost/latency** and oscillation (revise ↔ fail). → cap at 1 retry, deterministic stage first, skip VLM stage when deterministic stage is clearly OK.
4. Schema changes (G, ops) touch recipes/replay (principle 7). Need migration default for old recipes → T3 gate, human confirm, `--full` green.
5. Privacy: sending more derived data/overlays is fine, but logging reports/plans for eval must stay local and keys-free (principle 2).

---

## Suggested sequencing
1. Tier 0 (WB, rotate/denoise fixes, eval skeleton).
2. Tier 1 A, B, C, D, F, then run eval to quantify.
3. Tier 2 ops `tone`, `saturation`, `sharpen`, `straighten`, exposure rework.
4. Tier 3 G, H, then I, J.

## Critical files
- `vlm_photo_editor/templates/planner.py` (prompt), `agents/planner.py` (input encoding), `agents/critic.py`, `agents/edit_flow.py` (retry/critic node), `planner/compiler.py` (order lint/guards)
- `schema/op_catalog.py`, `schema/ops.py`, `schema/plan.py`, `schema/prefs.py`
- `ops/backends/pil_backend.py`, `ops/backends/cv_backend.py`, `ops/validator.py`
- new: `vlm_photo_editor/analysis/`, `schema/report.py`, `tests/eval/`
- Reuse: `register_op` (op_catalog), `DetectedSubject` injection pattern, crop-retry routing in `_route_after_compile`, `detection/` backends, `pipeline/plan_cache.py`.

## Verification (per item)
- Each code change: `bash agent_notes/utility_scripts/run_checks.sh` (T1; ruff known-red, no new errors in touched files); behaviour changes T2; schema/op additions T3 + `--full`.
- Tier 0: parametrized tests for WB direction, 16-bit-preserving rotate/denoise.
- Tier 1/2: eval harness pass-rate before vs after, same model, fixed seed where possible; report deltas, not "looks better".
- Critic v2: unit tests with synthetic before/after pairs (known clipping, known halo).
