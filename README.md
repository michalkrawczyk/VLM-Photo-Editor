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

AI-powered photo editor that proposes a human-readable plan, waits for your approval, then executes it deterministically. Originals are never altered.

**Flow:** Describe your edit → VLM generates a step-by-step plan → you approve or revise → ops execute → save a new file.

---

## Quick Start (local)

### Prerequisites

- Python 3.11+
- pip

### Install

```bash
git clone https://github.com/your-username/VLM-Photo-Editor.git
cd VLM-Photo-Editor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Install additional VLM provider adapters as needed:

```bash
pip install -r requirements-openai.txt       # GPT-4o
pip install -r requirements-huggingface.txt  # open-source models
```

Anthropic (Claude) is included in `requirements.txt` by default.

### Configure API Keys

```bash
cp .env.example .env
# Edit .env and fill in at least one key:
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-...
#   REPLICATE_API_TOKEN=r8_...    (for AI background replacement)
```

Key resolution order: **environment variable → OS keyring → `.env` file**. Keys can also be entered directly in the app's Settings panel (stored to OS keyring on desktop; session-only on headless/cloud environments).

### Run

```bash
streamlit run vlm_photo_editor/app/main.py
```

App opens at `http://localhost:8501`.

---

## Usage

1. **Upload** a JPEG, PNG, or RAW file using the sidebar uploader.
2. **Describe** your edit in plain language, e.g. `"replace background with a studio bokeh"`.
3. **Review** the generated plan — each step shows what will happen and why.
4. **Accept** to execute, or type a change request to revise the plan.
5. **Save** the result. A new file is written alongside the original; the original is untouched.

### Edit Modes

| Mode | What it does |
|------|-------------|
| Full Edit | All ops: exposure, crop, colour, background, etc. |
| Background Only | Limits planner to background-replacement ops |
| Frame Only | Limits planner to framing/crop ops |

### Accept Modes

| Mode | Behaviour |
|------|-----------|
| Manual | Nothing executes until you click **Accept Plan** |
| Auto-low | Auto-executes plans that contain only low-risk ops |
| Auto-all | Auto-executes all plans immediately |

---

## Docker

```bash
docker build -t vlm-photo-editor .

docker run -p 8501:8501 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e REPLICATE_API_TOKEN=r8_... \
  vlm-photo-editor
```

App available at `http://localhost:8501`.

Pass API keys via `-e` flags or `--env-file`. **Never bake keys into the image.**

### HuggingFace Docker Space

HF Docker Spaces route traffic to port **7860**. Override at runtime:

```bash
docker run -p 7860:7860 \
  -e STREAMLIT_SERVER_PORT=7860 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  vlm-photo-editor
```

For a Docker-mode HF Space, change the README frontmatter `sdk: streamlit` → `sdk: docker` and set `app_port: 7860`.

---

## HuggingFace Spaces

The app runs on HuggingFace Spaces without changes. Set secrets via **Space Settings → Repository secrets**:

| Secret | Required for |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Claude planner (default) |
| `OPENAI_API_KEY` | GPT-4o planner |
| `REPLICATE_API_TOKEN` | AI background replacement |

At least one VLM provider key is required. Background replacement is optional.

**In-app key entry** also works — open the Settings panel, enter a key in the API Keys section. On Spaces (no OS keyring), the key is stored in the session environment and active for the remainder of the session.

---

## Architecture

```
Planner (VLM) → HumanPlan → user approval → Compiler → OpGraph → Executor → Recipe
```

- **Planner** — LangGraph state machine; calls the configured VLM to generate a `HumanPlan` (list of human-readable steps with stable IDs).
- **Compiler** — validates the plan against the active op policy; produces a typed `OpGraph`.
- **Executor** — runs each `Op` deterministically using Pillow/OpenCV/NumPy; genAI ops call Replicate.
- **Recipe** — JSON sidecar recording every op, params, and (for genAI) model + seed. Replayable.

### Safety invariants

- Originals are never overwritten — saves write `{name}_edited{ext}`.
- API keys never appear in logs — `RedactionFilter` scrubs all log output.
- Plans are human-readable and revisable before any op runs.
- GenAI steps record model + prompt + seed for reproducibility.

---

## Development

```bash
pip install -r requirements_dev.txt
pytest                      # all tests
pytest -m "not slow"        # skip long-running tests
ruff check .
black --check .
```

Project structure: `vlm_photo_editor/{agents,app,config,imageio,ops,planner,recipe,schema,secrets}`. Each module has an `AGENTS.md` with per-module invariants and import rules.

Build plan and definition-of-done checklist: `plans/photo_editor_build_plan.md`.
