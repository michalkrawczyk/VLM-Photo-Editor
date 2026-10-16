---
title: VLM Photo Editor
emoji: 🖼️
colorFrom: blue
colorTo: green
sdk: streamlit
sdk_version: "1.36"
app_file: vlm_photo_editor/app/main.py
pinned: false
---

# VLM Photo Editor

A photo editor where a vision-language model **writes the plan and never touches the pixels**. You read the plan, steer it in plain language, approve it, and deterministic code executes it. Originals are never altered.

**Flow:** describe an edit → VLM proposes a step-by-step plan → you approve or revise → ops execute → a new file is saved, plus a replayable recipe.

---

## The experiment

This project is a test of one question:

> Can a language model **steer** an image edit precisely — what to change, where, and by how much — without regenerating the whole image?

Most AI editors hand the pixels to a generative model and accept what comes back. Here the VLM only emits a plan. A **chain of specialised models and backends** does the rest, and the chain exists to cover each model's known weak spots:

| Weakness | Covered by |
|---|---|
| VLMs localise poorly; bbox quality varies a lot between VLMs | A local detector (MediaPipe / YOLO-ONNX / U²-Netp) finds the subject *before* planning; the planner receives the bbox as context instead of guessing coordinates |
| VLMs judge exposure, white balance and noise by eye, inconsistently | A deterministic measurement block (histograms, WB, noise, sharpness) is passed into the planner prompt |
| VLM plans can contain invalid or out-of-range parameters | The compiler validates against the active policy; a bounded compile-and-repair loop hands errors back to the planner; nothing unvalidated executes |
| VLM output is non-deterministic | The plan is frozen as human-readable steps with stable IDs; execution is plain code; the recipe replays it |
| Generative models drift — they alter the subject or regenerate the frame | Generation is limited to a masked region (background only); colour/grain are matched and a seam metric gates the result; subject pixels are asserted byte-identical |
| Some image APIs accept no seed (OpenAI, Google) | Recorded as `seed=None` and treated as not replayable, never a fabricated seed |
| VLM self-grading is unreliable | The Critic runs deterministic checks first (a failed check fails without a VLM call); the VLM verdict comes second; parse/API errors become "uncertain", never a silent pass |
| Any one provider may be weak at one stage | Planner, Critic and preference aggregator are swappable per role (cloud or local); the detector is independent of the planner |

Because every handoff is a typed contract (plan → OpGraph → recipe), a bad result can be traced to a stage — the VLM's judgement, the detector's bbox, a compiled parameter, or the generator's fill. It also keeps the experiment comparable: swap one model, hold the rest fixed.

**What "precise" means here:** edits land in the requested region; pixels outside the mask are untouched; the same recipe replays to the same result; a change request alters only the affected plan step.

**Status:** the architecture is implemented. No benchmark results are published, so the hypothesis is **not** claimed proven.

**Note:** This code is written with assist of LLM models. Some of commands/skills/.md and other mechanisms for support agents are hidden or not published in evolved form.

---

## How it works

```
Detect subject → Measure image → Plan (VLM) → Approve → Compile → Execute → Critic → Recipe
   (local)        (NumPy/CV)     (HumanPlan)   (you)    (OpGraph)   (Pillow/CV    (checks +   (JSON,
                                                                     + masked      VLM)        replayable)
                                                                     genAI bg)
```

- **Planner** — VLM turns image + intent (+ detected subject, measurements, your preferences) into a `HumanPlan`: a diagnosis plus steps with stable IDs.
- **Compiler** — deterministic; validates the plan against the active op policy and produces a typed `OpGraph`.
- **Executor** — Pillow / OpenCV / NumPy for crop, rotate, white balance, exposure, tone, saturation, denoise, sharpen, framing. The only generative step is background replacement, restricted to a mask.
- **Critic** — optional before/after verification that can name the failing step.
- **Recipe** — JSON sidecar of every op and parameter; generative steps also record model + prompt + seed (where the provider supports one).

Photoshop is an optional backend for specific ops, never a requirement.

### Accept modes

| Mode | Behaviour |
|------|-----------|
| `manual` | Nothing executes until you approve. Change requests regenerate the plan and re-prompt |
| `auto_low` | Skips approval when every op is LOW risk |
| `auto_medium` | Skips approval when every op is LOW or MEDIUM risk |
| `full_auto` | Executes straight after compile, including genAI ops. Subject pixels are frozen and saves are non-destructive, so a bad result costs a rerun. In batch, results go to a mandatory post-run review before "Save All" |

### Features

- **Edit modes** — Full Edit, Background Only, Frame Only (limits what the planner may propose).
- **Composition-aware framing** — rule of thirds, golden ratio/spiral, portrait headroom, lead room, negative space, face-only and more, or let the planner recommend one.
- **Character Focus** — optional local subject detection to anchor crops. Without it, crop anchoring falls back to image centre.
- **Batch** — *Apply the same edit to every image* (one plan approved once, then adapted per image by the planner) or a per-image instruction for each file. A failure on one image never halts or drops the others.
- **Preferences** — explicit rules plus learned rules that stay pending until you approve them; all visible and removable in the panel.
- **RAW input** — via `rawpy` into a 16-bit array; JPEG and PNG supported.

---

## Quick start (local)

Requires Python 3.11+.

```bash
git clone https://github.com/michalkrawczyk/VLM-Photo-Editor.git
cd VLM-Photo-Editor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

`requirements.txt` includes the Anthropic adapter. Add others as needed:

| File | Adds |
|---|---|
| `requirements-openai.txt` | OpenAI planner/critic (the **default preset** is an OpenAI model — install this or pick a Claude preset in Settings) |
| `requirements-huggingface.txt` | local transformers models |
| `requirements-ollama.txt` / `requirements-llamacpp.txt` | local models via Ollama / llama.cpp |
| `requirements-mediapipe.txt` / `requirements-onnxruntime.txt` | subject-detection backends |

### API keys

```bash
cp .env.example .env
# fill in at least one VLM key, e.g. OPENAI_API_KEY or ANTHROPIC_API_KEY
# REPLICATE_API_TOKEN is only needed for AI background replacement
```

Resolution order: **environment → OS keyring → `.env`**. Keys can also be entered in the Settings panel (shown masked; stored in the OS keyring on desktop, session-only on headless/cloud). Keys never go into recipes, logs, prompts or session state.

### Subject detection models (optional)

Drop a model folder into `infer_models/` or use Settings → Detector models. `.tflite` runs on MediaPipe; `.onnx` with a sibling `classes.txt` runs as YOLO; a saliency model needs `model.json {"backend": "u2netp"}`. A misconfigured detector raises an error — it never silently falls back to another one. Details: [vlm_photo_editor/detection/AGENTS.md](vlm_photo_editor/detection/AGENTS.md).

### Run

```bash
streamlit run vlm_photo_editor/app/main.py
```

Opens at `http://localhost:8501`. Upload an image, describe the edit (e.g. `"replace the background with a studio bokeh"`), review the plan, accept or request changes, then save. Saves write a new `{name}_edited{ext}` file; the source is never overwritten.

Docker, Hugging Face Spaces, the Linux keyring note and troubleshooting: see [RUNBOOK.md](RUNBOOK.md).

---

## Safety invariants

- **Originals are sacred** — saves always write a new file.
- **Keys are secret** — a `RedactionFilter` scrubs log output; recipes store the model name only.
- **Plan before action** — the human-readable plan is the source of truth; compiled ops link back by step-ID and are never silently rewritten.
- **Subject pixels frozen** during background generation; only the masked region changes.
- **Fail loudly** — invalid plans or params are rejected with a clear error; failed steps are surfaced, not dropped or retried indefinitely.

## Limitations

- Google Imagen provider is currently non-functional (tracked as BG-B10).
- OpenAI image edits and Google record `seed=None`, so those generative steps are regenerated fresh on replay.
- OpenCV inpaint/denoise are 8-bit only; 16-bit input is downconverted for those ops.
- Stills only. No video, multi-user/cloud sync, mobile deployment or colour-managed print workflows.

## Development

```bash
pip install -r requirements_dev.txt
bash agent_notes/utility_scripts/run_checks.sh   # lint + format + docstyle + tests
pytest -m "not slow"                             # fast tests
pytest -m e2e tests/e2e/ -v                      # live-browser tests; real API calls, costs money
```

Project notes, per-module invariants and conventions live in [agent_notes/](agent_notes/index.md) and each module's `AGENTS.md`. Build plan and definition-of-done: [plans/photo_editor_build_plan.md](plans/photo_editor_build_plan.md).
