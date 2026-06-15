# VLM Photo Editor — Implementation Plan

A build spec for an implementing LLM (target: Sonnet 4.6). Work **one step at a time**. Do **not** start a step until the previous step's Definition of Done passes.

See `CLAUDE.md` §Non-negotiable principles for all global invariants. Two invariants specific to this plan:
- **Contracts before behavior.** Schemas defined first; never change a contract without updating all dependents.
- **DoD gates progress.** Each step ships behind its Definition of Done before the next begins.

**Sequencing note.** Ship P0 and P1 together (contracts + IO). Slot P0.5 (UI shell) right after P0 to lock look-and-feel against stubs before backend work; real wiring lands in P7. Then P2 → P10 strictly, gating on each DoD.

---

## Step P0 — Scaffold, Contracts, Secrets

**What.** Repo structure; `config` (policy modes, model registry, thresholds); `SecretStore` + redaction filter; `schema` package — all Pydantic models and enums.

**Why.** Every later module imports `schema` and the image/secret contracts. Defining contracts and key-safety on day one is the primary defense against downstream drift and leaks.

**Key functionality.** `SecretStore.get(provider)` with env→keyring→`.env` precedence; masked key entry in settings; schemas for `Op`, `OpGraph`, `HumanPlan` (steps carry stable IDs), `Recipe`, `Preferences`; enums `OpName`, `Backend`, `FramingMode`, `RiskTier`; model registry mapping role→model (switchable).

**User-facing result.** Nothing visible to edit yet, but the user can enter API keys safely — masked, validated, never stored in plaintext. Foundation for trust.

**Definition of Done.**
- [x] Schemas validate the sample fixtures.
- [x] A key entered via the UI is retrievable through `SecretStore`, shown masked, and absent from logs (redaction test passes).
- [x] Changing a role→model mapping in config takes effect (unit test).

---

## Step P0.5 — UI Boilerplate / Shell

**What.** A runnable Streamlit shell with the full intended layout and all controls present, wired to mock/stub data — no real backend. Real wiring happens later in P7.

**Why.** Lets the coder lock in look-and-feel and the functional layout at the earliest stage, before backend work, so UI decisions don't churn after logic is built. Cheap to iterate now, expensive to restructure later.

**Key functionality.** Page layout and panels stubbed: upload area; before/after preview (placeholder images); plan display with expandable ops (mock plan); accept-mode toggle (auto/manual); the three mode buttons (bg-only / frame-only / full); chat box for change requests; framing-mode picker; bbox-draw canvas; preferences panel (explicit + learned); role-model switchers; masked API-key settings; save button. All controls emit events/log intents against stubs; no image is actually processed.

**User-facing result.** A clickable app that looks and feels like the final product — the coder (and stakeholders) can adjust layout, controls, naming, and flow before committing backend effort.

**Definition of Done.**
- [x] App launches in the browser.
- [x] Every planned control is present and interactive against stubs.
- [ ] Layout and component choices are reviewed/approved.
- [x] No control performs real processing yet; placeholders are clearly marked.
- [x] Each control's component contract (what it sends/expects) is noted so P7 wires real logic without restructuring the UI.

---

## Step P1 — ImageIO and ImageContainer

**What.** Loaders/savers for RAW (rawpy), JPG/PNG (PIL). `ImageContainer` = pixels + bit-depth + ICC profile + metadata. Never-override save.

**Why.** Correct color and bit-depth handling is foundational; mishandling RAW corrupts every later result.

**Key functionality.** RAW demosaic → 16-bit linear; ICC profile preserved/converted; format detection; `save` refuses the source path and writes a new file with a clear naming scheme.

**User-facing result.** Opens RAW/JPG/PNG with no color or quality loss; originals are provably safe.

**Definition of Done.**
- [x] Round-trip tests pass for each format.
- [x] RAW yields 16-bit with profile intact.
- [x] Attempting to save over the source raises.

---

## Step P2 — Ops Executor, Backends, Validator

**What.** Per-op functions on `pil`/`opencv`/`rawpy` backends (`genai`/`photoshop` stubbed). Backend registry + policy resolver. Validator. Bounding-box → region mask.

**Why.** The deterministic edit engine. Validation stops VLM-hallucinated ops/params from ever executing.

**Key functionality.** `Executor.apply(container, opgraph)`; bounds-checked ops (crop, rotate, white-balance, exposure, denoise, mask, region edit); region edits confined to a user- or VLM-supplied bbox.

**User-facing result.** Edits apply predictably; bad instructions are caught, not run.

**Definition of Done.**
- [x] An op-graph applies to the expected golden image.
- [x] Unknown ops or out-of-bounds params are rejected with a clear error.
- [x] A bbox region edit changes only pixels inside the box.

---

## Step P3 — Recipe / Non-destructive Store

**What.** Serialize/deserialize the op-graph to a sidecar; `render(recipe)`; undo/redo; variant branches; export-as-preset.

**Why.** Delivers the non-destructive promise plus reproducibility, undo, variants, and batch presets — for free, from one mechanism.

**Key functionality.** Sidecar (`<name>.edit.json`; XMP for RAW interop); deterministic `render`; branch v1/v2; re-render at any size/format; reapply recipe to other images.

**User-facing result.** Undo anything, keep multiple versions, reuse an edit as a preset; the original is never touched.

**Definition of Done.**
- [x] `render` is deterministic across runs.
- [x] Original is byte-identical after edits.
- [x] Undo restores the prior state.
- [x] A saved preset reapplies correctly to a second image.

---

## Step P4 — Planner (two-stage), Modes, Accept Toggle

**What.** VLM produces a concise human-readable plan → compiler turns it into an `OpGraph` → executor runs it. Mode buttons (Fix background only / Frame only / Full changes). Three accept modes (`AcceptMode` enum: `manual` / `auto` / `full_auto`) with an editable plan. Step-ID linkage. Preferences injection. Allowed-op constraint.

**Why.** The core agent loop. Human-readable-first prevents opaque automation and is the main anti-drift lever for the editing logic itself.

**Accept modes.**
- **`manual`** — human in the loop: nothing executes until the user explicitly approves. After the plan is shown the app asks for a decision: **accept** or **request changes**. If the user types requested changes in the chat box, the planner regenerates the plan incorporating that feedback and asks for a decision again. This loop repeats — regenerate → present → ask — until the user approves.
- **`auto`** — skips human approval when all compiled ops are LOW risk; still prompts for HIGH/DESTRUCTIVE ops.
- **`full_auto`** — skips human approval unconditionally; plan is compiled and executed immediately after generation, regardless of risk tier.

**Key functionality.** Numbered human plan with short "why" per step; compiled ops shown as an expandable under each step (verify mapping); manual plan editing; chat-driven change requests that regenerate the plan and re-prompt for approval; risk-tier gating for `auto` mode; `AcceptMode` enum (`schema/ops.py`) used by graph and UI.

**User-facing result.** Sees a clear plan before anything happens. In manual mode, can keep asking for changes in chat and gets a revised plan each time, approving only when satisfied — then it runs. Auto and full-auto modes reduce friction for trusted or low-stakes workflows.

**Definition of Done.**
- [ ] End-to-end on a sample image in all three accept modes.
- [x] In manual mode, no op executes before explicit approval.
- [x] A chat-box change request produces a regenerated plan and a fresh approval prompt, looping until approval is given.
- [x] Each human step maps to ops by stable ID.
- [x] Editing the plan changes the executed ops.
- [x] The active mode's allowed-op set is respected.

---

## Step P5 — Framing Module

**What.** Subject detection (face/saliency) + composition mode → crop box or outpaint request. Optional secondary target ratio.

**Why.** Framing must be subject-aware, not ratio-only; prevents head-clipping and gives photographic intent.

**Key functionality.** Modes: rule of thirds, golden ratio, golden spiral, center/symmetry, portrait headroom, face-only, negative space, fill frame, lead/gaze room, horizon level + horizon-on-third. Outpaint fallback when a crop would lose needed content.

**User-facing result.** Pick a photographic framing intent and get a correct, subject-aware crop.

**Definition of Done.**
- [ ] Each mode produces a sane crop on face and scene fixtures with no head-clipping.
- [ ] Outpaint is requested when a crop cannot satisfy the mode.

---

## Step P6 — Background genAI Pipeline

**What.** Generator backend + composite → color-match → grain-match → seam-blend → candidates → seam-quality gate.

**Why.** This is the highest quality-risk area. Compositing plus matching is what prevents the "pasted-in / fake" look.

**Key functionality.** Freeze subject; generate N candidates (different seeds) inside the bbox/mask; LAB mean/std color transfer from a border ring; grain/noise match to subject; feathered seam blend; seam metric (edge gradient discontinuity) gate with seed re-roll, then flag for manual if still failing; store seed/prompt/model in the recipe.

**User-facing result.** Realistic background edits, several options to choose from, fully reproducible.

**Definition of Done.**
- [x] Subject pixels are unchanged (asserted).
- [x] Seam metric is under threshold or the result is flagged.
- [x] N candidates are returned.
- [x] The recipe reproduces a chosen candidate exactly.

---

## Step P7 — Streamlit UI

**What.** Upload; before/after preview; plan display with expandable ops; bbox-draw canvas; preferences panel; role-model switchers (planner / executor-genAI); save button.

**Why.** Assembles the system into the usable product.

**Key functionality.** Drawable canvas for bbox region selection; accept-mode toggle; the three mode buttons; masked API-key settings; save writes a new file via the recipe.

**User-facing result.** The full workflow runs in the browser end to end.

**Definition of Done.**
- [x] User can upload → see plan → edit/accept → preview before/after → save a new file.
- [x] Switching planner and execution models works.
- [x] A bbox drawn in the UI drives the region edit.

---

## Step P8 — Preferences Learning Loop

**What.** Two stores — explicit (user-authored) and learned (system-derived). Delta capture on accept/reject/edit. LLM aggregation into candidate rules. User approval. Injection into the planner.

**Why.** Turns stored preferences into adaptive ones without silent drift.

**Key functionality.** Log proposed-vs-final deltas per edit; periodically summarize into candidate rules; user approves before a learned rule activates; per-rule on/off; explicit prefs override learned on conflict.

**User-facing result.** The app gradually matches the user's style — with consent, and fully inspectable/editable.

**Definition of Done.**
- [ ] Repeated edits produce candidate rules.
- [ ] Approving a rule changes the next plan.
- [ ] Rules toggle on/off.
- [ ] Explicit beats learned on conflict.

---

## Step P9 — Optional Layers: Critic, PS-strict, MCP Bridge

**What.** Critic VLM as an optional checkbox. PS-strict mode constraining the planner to Photoshop-expressible ops. No-PS mode. MCP server wrapping UXP/ExtendScript with capability discovery.

**Why.** An optional second-opinion quality gate; Photoshop power without making PS a hard dependency.

**Key functionality.** Critic verifies result vs intent and loops on failure; PS op vocabulary is fed into the planner prompt so only PS-expressible edits are proposed; mode disables cleanly with a clear message when PS is unavailable.

**User-facing result.** Optional automatic quality check; the option to force pure-Photoshop edits when desired.

**Definition of Done.**
- [ ] With Critic on, an intentionally-bad edit is caught.
- [ ] PS-strict only ever proposes PS-expressible ops.
- [ ] The mode disables with a clear message when PS is absent.

---

## Step P10 — Hardening

**What.** Async job queue for large RAW; plan caching; cheap cost-router triage; full log-redaction audit; error surfaces.

**Why.** Performance, cost, robustness, and final security closure.

**Key functionality.** Non-blocking processing with progress; cache keyed by image hash + mode + prefs version; a cheap router that skips full VLM planning for trivial modes; an audit confirming zero key leakage.

**User-facing result.** Responsive on large files, cheaper to run, reliable.

**Definition of Done.**
- [ ] A large RAW processes without blocking the UI (progress shown).
- [ ] A cache hit avoids re-planning.
- [ ] The redaction audit finds zero key leakage across logs and errors.

