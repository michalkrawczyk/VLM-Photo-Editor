# background — Agent Notes

**Role:** genAI background pipeline — generate candidates, composite, color/grain-match, and gate on seam quality.

## Import rules
- May import: `schema`, `config`, `imageio`, `ops`, stdlib, `numpy`, `scipy`, `scikit-image`
- May import provider SDKs lazily inside provider classes (`replicate`, `openai`, `diffusers`, `google-generativeai`)
- Must NOT import: `planner`, `secrets` directly in module-level code (keys resolved inside provider classes)

## Critical invariants
- **Subject pixels frozen:** after compositing, assert that every pixel outside the mask is byte-identical to the input. Test: `test_background.py::test_subject_pixels_unchanged_after_composite`. This is a hard assertion, not a warning.
- **Provider honours the mask (BG-P3):** a provider must regenerate *only* the masked region — via a native mask/inpaint parameter, or by only ever sending the model the masked crop (see `GoogleProvider`). Re-masking with `composite()` afterwards is not a substitute. A provider/model that cannot do this (e.g. Qwen2.5-VL, which emits text) raises in `generate()`; it must not return a full-frame regeneration.
- **Seed/model/prompt stored:** every candidate generation records `model`, `prompt`, and `seed` in the `Recipe`. A provider whose API accepts no seed (OpenAI images.edit, Google Imagen edit) records `seed=None` — never a fabricated `random.randint` (BG-P2); such a step is regenerated fresh on replay, not falsely reproduced.
- **Seam gate:** if the seam metric exceeds threshold after seed re-roll, flag the result for manual review — do not silently pass a bad composite. Threshold is `settings.seam_threshold` (default 0.03, `VLM_SEAM_THRESHOLD` to override) on the metric's 0-~0.1 scale; the flag reaches `ExecutionResult.genai_needs_manual` and the UI warning (BG-P1).
- **N candidates returned:** provider must return exactly N candidates (different seeds); caller picks one.
- **All candidates scored and returned:** `select_best` returns every `ScoredCandidate`, not just the winner — the caller (UI) may override the pick via `override_index`.

## Provider architecture

New genAI providers live in `providers/`. To add a new provider:
1. Subclass `GenAIProvider` from `providers/base.py`
2. Implement `generate(container, mask, prompt, model, step_id, n, seed, **kwargs) -> list[Candidate]`
3. Add a prefix (e.g. `myco:`) and register it in `providers/__init__.py::provider_name_for()` and `get_provider()`
4. Add `SecretStore.has("myco")` check to `available_genai_providers()`

## Files

| File | Responsibility |
|------|---------------|
| providers/base.py | `GenAIProvider` ABC; `Candidate` dataclass |
| providers/replicate.py | `ReplicateProvider` — Replicate inpainting API |
| providers/huggingface.py | `HuggingFaceProvider` — local FLUX.1-Fill-dev / Qwen2.5-VL |
| providers/openai_provider.py | `OpenAIProvider` — OpenAI images.edit (gpt-image-1) |
| providers/google_provider.py | `GoogleProvider` — Google Imagen via generativeai SDK. Honours the mask by sending only its cropped bounding box (no native mask param). **Untested (BG-B10):** calls SDK symbols absent from `google-generativeai` |
| providers/__init__.py | `get_provider(model)`, `available_genai_providers()`, `provider_name_for()` |
| generator.py | Back-compat shim; re-exports `Candidate`, `Generator(ReplicateProvider)` |
| composite.py | LAB mean/std color transfer from border ring; grain/noise match to subject; feathered seam blend |
| quality.py | Edge-gradient seam metric; seed re-roll on failure; flag-for-manual fallback |

## Model naming convention

| Prefix | Provider | Example |
|--------|----------|---------|
| *(none)* | Replicate | `black-forest-labs/flux-fill-dev` |
| `hf:` | HuggingFace local | `hf:black-forest-labs/FLUX.1-Fill-dev` |
| `openai:` | OpenAI images API | `openai:gpt-image-1` |
| `google:` | Google Imagen **(not working — BG-B10)** | `google:imagen-3.0-generate-002` |

## Tests
- Location: `tests/unit/test_background.py`
- Fixtures: `tests/fixtures/images/sample.jpg` + a mock provider injected via `provider=` kwarg
- Key scenarios: subject pixels unchanged after composite; seam metric gates on threshold; N candidates returned; scored candidate list returned for manual override
- Not covered: "chosen candidate reproducible from stored seed" — OpenAI/Google accept no seed (BG-P2)

## Common mistakes

| Wrong | Correct |
|-------|---------|
| Modify pixels outside the mask during composite | Apply color/grain transfer only inside the masked region |
| Skip seed storage when a candidate is accepted | Always store seed/model/prompt before returning any candidate |
| Pass the seam metric check with a soft warning | Hard gate: re-roll seed, then flag for manual if still failing |
| Color transfer in RGB space | Convert to LAB first (`skimage.color.rgb2lab`) for perceptually correct transfer |
| Import `replicate` at module level | Import lazily inside `ReplicateProvider._get_client()` |
| Call `generator=` in `run_background_pipeline` | Use `provider=` kwarg |
| Hardcode `threshold=10.0` / `feather_px=20` | Leave the arg `None`; defaults come from `get_settings()` |
