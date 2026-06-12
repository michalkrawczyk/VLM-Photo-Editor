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
