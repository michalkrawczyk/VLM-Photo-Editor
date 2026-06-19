# Future Improvements

Deferred features and libraries that are intentionally out of scope for the base implementation but worth revisiting once the core is stable.

---

## Local Face Detection & Subject Segmentation

**Library:** `mediapipe>=0.10`

**Why deferred:** The base implementation delegates face detection and subject masking to the VLM via vision input. mediapipe is a purely local, zero-API-cost alternative that would reduce latency (sub-10 ms vs. ~500 ms API round-trip) and eliminate per-image cost for these geometric ops.

**Trigger for adoption:** Once the VLM-based path is proven correct and the op interface is stable, mediapipe can be dropped in as the geometry backend while the VLM retains high-level planning responsibility.

**Install:** `pip install mediapipe>=0.10`

**Alternative considered:** `face-recognition` (dlib) — heavier build dependency (requires CMake and dlib compile); mediapipe is pip-installable and covers both detection and segmentation in one package.

---

## Structured / JSON Logging

**Library:** `structlog>=24.0`

**Why deferred:** The only current logging requirement is API-key redaction, which stdlib's root-level `logging.Filter` covers without extra dependencies (see `stack.md`). structlog's explicit processor pipeline becomes worth the dependency if the project adds a remote log sink (e.g. Loki, Datadog), needs machine-parseable JSON output, or wants structured key-value event dicts across the codebase.

**Trigger for adoption:** When a log aggregation service is wired up, or when structured event fields (e.g. `image_id`, `op_name`, `duration_ms`) are needed alongside the message.

**Install:** `pip install structlog>=24.0`

---

## Precision Codebase Exploration (Explore Agent Replacement / Improvement)

**Problem:** The Explore agent summarizes files rather than returning verbatim content, causing precision loss (exact field names, signatures) during planning. The main context must then re-read the same files directly, doubling reads.

**Option A — Richer AGENTS.md (low-cost, immediate):**
Extend each `vlm_photo_editor/<module>/AGENTS.md` to include actual exported function/class signatures and key field names (not just prose descriptions). An agent reads the AGENTS.md first for precise quick-reference, then reads only the specific file sections it still needs verbatim. No tooling changes required.

**Option B — Auto-generated API manifest:**
Extend `agent_notes/generate_module_map.py` to emit a `module_api.json` alongside the module map, containing exported symbols + signatures per module. An agent queries this JSON for discovery, then reads the target file directly — no summarization step.

**Option C — Annotated "context files" in plan sections:**
Add a "Key files to read for context" subsection to each P-step in `plans/photo_editor_build_plan.md`. Eliminates discovery entirely for planned work; an agent reads the listed files verbatim and proceeds without an Explore pass.

**Trigger for adoption:** Any of these pays off when P-step planning takes more than one round of clarification reads. Option A (richer AGENTS.md) is the cheapest and can be done incrementally as each module stabilizes. Option B is worth doing once all core modules (P0–P6) are complete.

---

## Pre-VLM Face Anonymization

**Problem:** Sending user photos to external VLM/planner APIs (Anthropic, Replicate, etc.) exposes identifiable faces to third-party systems. Users may not expect or consent to this.

**Mechanism:** Before encoding any `ImageContainer` for a VLM API call, run a local face-detection pass (mediapipe or similar — see Local Face Detection above) and replace each detected face region with a neutral placeholder (solid fill, Gaussian blur, or a synthetic face via a local diffusion model). This anonymized copy is sent to the API; the original pixels are never transmitted. The anonymization is ephemeral — it exists only in the encoded bytes, never written to disk.

**Integration point:** `Planner._encode_image` (currently `vlm_photo_editor/agents/planner.py:119`). Add an optional `anonymize_faces: bool` parameter (default `False` until mediapipe is added as a dependency). The session state or `AppSettings` exposes this toggle to the user.

**Scope:** Applies to the planning step only. The executor operates entirely locally on the original pixels.

**Constraints:**
- Anonymization must not alter bounding-box geometry visible to the VLM (blurring is safer than cropping).
- The redaction must be reversible to zero: the unmodified `ImageContainer` must remain accessible in session state after the API call.
- Log that anonymization ran, but never log which regions were masked (face coordinates are PII-adjacent).

**Trigger for adoption:** When the app handles photos of real people in production, or when a user requests a privacy mode. Should be implemented alongside the mediapipe integration since both share the same face-detection pre-pass.
