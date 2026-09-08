# app — Agent Notes

**Role:** Streamlit UI — the only layer that touches the user directly. Assembles all modules into the runnable product.

## Import rules
- May import: all sibling modules, `streamlit`, `streamlit-drawable-canvas`
- Must NOT import: raw `anthropic`/`openai` SDKs directly — go through `models/registry.py`

## Critical invariants
- **No secrets in session state:** `st.session_state` must never hold a raw API key. Keys are resolved via `SecretStore` at call time only.
- **RedactionFilter first:** `secrets.redaction.RedactionFilter` is added to the root logger at the top of `main.py` before any other import that might trigger logging.
- **Stubs boundary (P0.5 vs P7):** `stubs.py` provides the complete mock surface for P0.5. In P7 it is replaced by real wiring. Never mix stubs and real backends in the same session — check the active mode.
- **Nothing executes without approval (manual mode):** the accept button is the only trigger for `Executor.apply()`. A plan display must never auto-execute.

## Files

| File | Responsibility |
|------|---------------|
| main.py | Entrypoint (`streamlit run`); wires `RedactionFilter`; page layout |
| state.py | Session state management — typed accessors, no raw key storage |
| stubs.py | Mock data for P0.5 (plan, ops, images); replaced in P7 |
| components/upload.py | File upload widget |
| components/preview.py | Before/after side-by-side preview |
| components/plan_view.py | Plan display with expandable compiled ops per step |
| components/canvas.py | `streamlit-drawable-canvas` bbox selection |
| components/prefs_panel.py | Explicit + learned rules panel; per-rule toggles |
| components/batch_review.py | Post-run batch review: summary, review queue, Save All, Needs Attention |
| components/settings.py | Masked API-key entry; role→model switchers; mode buttons |

`main.py:_render_batch_panel` has a "Apply the same edit to every image" checkbox:
Mode A (`_render_batch_mode_a`) = one shared instruction, plan approved once, then
`pipeline.batch.apply_plan_to_batch` recompiles + executes it per image (no VLM
call); Mode B (`_render_batch_mode_b`) = per-image instruction boxes, `run_batch`
per image, then the review queue.

## Tests
- UI components are tested via the integration test: `tests/integration/test_pipeline.py`
- P0.5 DoD: every control present and interactive against stubs; no real processing triggered

## Common mistakes

| Wrong | Correct |
|-------|---------|
| `st.session_state["api_key"] = key` | Resolve key in `SecretStore.get()` at call time; never cache in state |
| `import logging` before `RedactionFilter` is wired | Wire filter at the very top of `main.py` before any other import |
| Call `Executor.apply()` on plan display | Only call on explicit user accept action |
| Use a real backend while stubs are active | Check `state.is_stub_mode()` before dispatching |
