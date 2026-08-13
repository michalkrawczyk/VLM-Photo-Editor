# RUNBOOK

Operational guide for running VLM Photo Editor.

---

## Prerequisites

- Python 3.12+
- At least one VLM provider API key (Anthropic, OpenAI, or HuggingFace)
- `REPLICATE_API_TOKEN` only if using AI background replacement

---

## Local Setup

```bash
git clone <repo-url>
cd VLM-Photo-Editor
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```

Default `requirements.txt` includes `langchain-anthropic`. For other providers:

```bash
pip install -r requirements-openai.txt       # GPT-4o
pip install -r requirements-huggingface.txt  # open-source models
```

### Configure API Keys

```bash
cp .env.example .env
# Edit .env:
#   ANTHROPIC_API_KEY=sk-ant-...
#   OPENAI_API_KEY=sk-...         (optional)
#   REPLICATE_API_TOKEN=r8_...    (optional; needed for background replacement)
```

Key resolution order: **environment variable → OS keyring → `.env` file**

Keys can also be entered in the app's Settings panel — stored to OS keyring on desktop, session-only on headless/cloud.

### Run

```bash
streamlit run vlm_photo_editor/app/main.py
```

Opens at `http://localhost:8501`.

---

## Docker

```bash
docker build -t vlm-photo-editor .

docker run -p 8501:8501 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e REPLICATE_API_TOKEN=r8_... \
  vlm-photo-editor
```

App at `http://localhost:8501`. Pass keys via `-e` or `--env-file`. Never bake keys into the image.

### HuggingFace Spaces (Docker mode)

HF Spaces route to port 7860:

```bash
docker run -p 7860:7860 \
  -e STREAMLIT_SERVER_PORT=7860 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  vlm-photo-editor
```

Set secrets via **Space Settings → Repository secrets**:

| Secret | Required for |
|--------|-------------|
| `ANTHROPIC_API_KEY` | Claude planner |
| `OPENAI_API_KEY` | GPT-4o planner |
| `REPLICATE_API_TOKEN` | AI background replacement |

---

## Usage Flow

1. **Upload** — JPEG, PNG, or RAW file via sidebar uploader
2. **Describe** — plain-language edit request, e.g. `"replace background with studio bokeh"`
3. **Review plan** — each step shows what will happen and why
4. **Accept** — click Accept to execute, or type a change request to revise
5. **Save** — writes `{name}_edited{ext}` alongside the original; original untouched

### Edit Modes

| Mode | Description |
|------|-------------|
| Full Edit | All ops: exposure, crop, colour, background |
| Background Only | Limits planner to background-replacement ops |
| Frame Only | Limits planner to framing/crop ops |

### Accept Modes

| Mode | Behaviour |
|------|-----------|
| Manual | Nothing executes until you click **Accept Plan** |
| Auto-low | Auto-executes plans containing only low-risk ops |
| Auto-all | Auto-executes all plans immediately |

---

## Development

```bash
pip install -r requirements_dev.txt
```

### Tests

```bash
pytest                      # all tests
pytest -m "not slow"        # skip long-running tests
pytest -m integration       # integration tests only
pytest --cov=vlm_photo_editor --cov-report=term-missing
```

### Linting & Formatting

```bash
ruff check .
black --check .
isort --check .
```

Fix in-place:

```bash
ruff check --fix .
black .
isort .
```

---

## Linux Keyring Note

On **Linux desktop** (GNOME/KDE), OS keyring requires an active graphical session (D-Bus). On **headless Linux**, keyring falls back to `.env`. To enable encrypted-file storage on headless:

```bash
pip install keyrings.alt
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No VLM provider configured` | Set at least one of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| `rawpy` import error | `pip install rawpy>=0.23`; needs LibRaw (included in wheel) |
| Streamlit port in use | `streamlit run vlm_photo_editor/app/main.py --server.port 8502` |
| Background replacement fails | Set `REPLICATE_API_TOKEN`; op requires network access |
| Keyring error on headless | Ignore (falls back to `.env`) or `pip install keyrings.alt` |
| `opencv` import error | Ensure `opencv-python-headless` installed, not `opencv-python` |
