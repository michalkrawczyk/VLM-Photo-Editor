# Technology Stack

Choices mapped to the build plan's requirements. Each entry notes the primary reason for selection and the main alternative considered.

---

## Contracts & Validation

| Library | Version | Role |
|---------|---------|------|
| **pydantic** | `>=2.7` | All `schema/` models — `Op`, `OpGraph`, `HumanPlan`, `Recipe`, `Preferences`. v2 chosen for `model_validator`, discriminated unions, and JSON schema export. |

Alternative: `dataclasses` + `jsonschema` — rejected because Pydantic gives validation, serialization, and schema generation in one place.

---

## Secrets & Configuration

| Library | Version | Role |
|---------|---------|------|
| **python-dotenv** | `>=1.0` | Loads `.env` as the lowest-priority fallback in `SecretStore`. |
| **keyring** | `>=25.0` | OS keyring as the middle tier. Cross-platform (SecretService/Keychain/Windows Credential Manager). |

Cross-platform status:

| Platform | Backend | Notes |
|----------|---------|-------|
| **Windows** | Windows Credential Manager (`WinVaultKeyring`) | Works natively, no setup |
| **macOS** | macOS Keychain | Works natively, no setup |
| **Linux desktop** | SecretService (GNOME Keyring / KWallet) via D-Bus | Requires an active graphical session |
| **Linux headless** | None by default | Falls back gracefully to `.env` tier; optionally install `keyrings.alt` for encrypted-file storage |

---

## Logging & Redaction

No third-party logging library. The only logging requirement in the build plan is **redaction** (Global Invariant #2: no API key ever appears in a log).

This is implemented as a stdlib `logging.Filter` on the root logger:

```python
class RedactionFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'sk-[A-Za-z0-9]{20,}', '[REDACTED]', str(record.msg))
        record.args = ()  # prevent deferred formatting from exposing raw args
        return True

logging.getLogger().addFilter(RedactionFilter())
```

A root-logger filter fires for every `LogRecord` before any handler (existing or future) dispatches it — the same "no unguarded sink" guarantee that was cited for structlog. No extra dependency needed.

Alternatives considered and rejected:
- **structlog** — justified if structured/JSON logging or a remote sink is needed; see `future_improvements.md`.
- **loguru** — per-sink filter hooks can't guarantee universal redaction.

---

## Image I/O

| Library | Version | Role |
|---------|---------|------|
| **Pillow** | `>=10.3` | JPEG/PNG load, save, ICC profile preservation, mode conversion. |
| **rawpy** | `>=0.21` | RAW demosaic → 16-bit linear `numpy` array. Wraps LibRaw. |

Alternative for RAW: `imageio` with rawpy plugin — adds an indirection layer with no benefit here.

---

## Image Processing (deterministic ops)

| Library | Version | Role |
|---------|---------|------|
| **numpy** | `>=1.26` | Array substrate for all pixel operations. |
| **opencv-python-headless** | `>=4.9` | Ops where OpenCV outperforms Pillow: bilateral denoise, Canny edge detection for seam metric, contour-based masking. Headless variant avoids GUI deps. |
| **scipy** | `>=1.13` | Gaussian blur for feathered seam blend; frequency analysis for grain matching. |
| **scikit-image** | `>=0.23` | LAB colorspace conversion for background color transfer; structural similarity (SSIM) for seam quality metric. |

---

## VLM / AI Planner

| Library | Version | Role |
|---------|---------|------|
| **langchain** | `>=0.2` | Base package — chains, prompt templates, output parsers used across Planner, Critic, and preference-aggregation modules. |
| **langgraph** | `>=0.2` | State-machine orchestration for the two-stage Planner (plan → critique → replan) and multi-step Critic flows. Provides state graphs, conditional edges, and streaming. |
| **langchain-anthropic** *(optional)* | `>=0.2` | Claude adapter (`ChatAnthropic`). Install via `requirements-anthropic.txt`. |
| **langchain-openai** *(optional)* | `>=0.2` | OpenAI/GPT adapter (`ChatOpenAI`). Install via `requirements-openai.txt`. |
| **langchain-huggingface** *(optional)* | `>=0.1` | HuggingFace adapter for local/open-source models. Install via `requirements-huggingface.txt`. |

At least one provider adapter must be installed. LangChain/LangGraph is preferred over the bare `anthropic` SDK because it provides provider-agnostic `BaseChatModel` interfaces, built-in tool-call handling, and structured output parsing. The model registry in `models/registry.py` constructs any `BaseChatModel` so the provider is swappable with a config change.

---

## Background Generation (genAI)

| Library | Version | Role |
|---------|---------|------|
| **replicate** | `>=0.30` | Background inpainting via Stable Diffusion inpainting models (e.g. `stability-ai/stable-diffusion-inpainting`). Seed control is native; model + seed stored in the recipe for reproducibility. |

Alternative: `fal-client` — similar capability, slightly less mature Python SDK at time of writing.
Alternative: Stability AI direct REST API (`requests`) — more control but more boilerplate; replicate SDK handles retries and streaming.

---

## UI

| Library | Version | Role |
|---------|---------|------|
| **streamlit** | `>=1.36` | Main app framework. Session state, layout, file uploader, sidebar. |
| **streamlit-drawable-canvas** | `>=0.9.4` | Bbox draw widget for region selection in P0.5 and P7. Returns bounding-box coordinates as a dict that maps directly to the `Op` schema. |

Alternative for UI: Gradio — less layout control; Streamlit's component model is better suited to a multi-panel editor.

---

## Async / Job Queue (P10)

| Library | Version | Role |
|---------|---------|------|
| **anyio** | `>=4.3` | Async primitives for the P10 job queue (non-blocking RAW processing). |

Streamlit re-executes each script in its own thread, so there is no single persistent event loop. `asyncio.run()` creates and destroys a loop per call; nesting it within a running loop raises `RuntimeError`. anyio's `anyio.to_thread.run_sync` / `anyio.from_thread.run_sync` are designed for exactly this thread-bridge pattern. anyio is also backend-agnostic (asyncio or trio), so `pytest-anyio` can run tests without pinning a specific runner.

Streamlit's own `st.cache_data` handles plan caching keyed by image hash + mode + prefs version.

---

## Dev / Test

See `requirements_dev.txt`. Summary:

| Tool | Role |
|------|------|
| **pytest** | Test runner |
| **pytest-cov** | Coverage |
| **pytest-asyncio** | Async test support for P10 |
| **black** | Formatter |
| **isort** | Import sorter |
| **ruff** | Fast linter (replaces flake8 + pylint for most checks) |
| **pydocstyle** | Docstring convention enforcement |
