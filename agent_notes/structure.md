# Project File Structure

Modules: `config` · `secrets` · `schema` · `imageio` · `models` · `ops` · `detection` · `background` · `agents` · `planner` · `recipe` · `preferences` · `pipeline` · `templates` · `app`

For per-module invariants, import rules, and common mistakes see `AGENTS.md`, where present: `agents`, `secrets`, `ops`, `background`, `detection`, `imageio`, `schema`, `planner`, `app`. Not yet written for `config`, `pipeline`, `recipe`, `preferences`, `models`, `templates`.

---

```
vlm_photo_editor/
│
├── config/
│   ├── __init__.py
│   ├── policy.py
│   ├── registry.py
│   └── settings.py
│
├── secrets/
│   ├── __init__.py
│   ├── store.py
│   └── redaction.py
│
├── schema/
│   ├── __init__.py
│   ├── ops.py
│   ├── plan.py
│   ├── recipe.py
│   └── prefs.py
│
├── imageio/
│   ├── __init__.py
│   ├── container.py
│   ├── loaders.py
│   └── savers.py
│
├── models/
│   ├── __init__.py
│   └── registry.py
│
├── ops/
│   ├── __init__.py
│   ├── constants.py
│   ├── executor.py
│   ├── mask.py
│   └── validator.py
│
├── detection/
│   ├── __init__.py
│   ├── _common.py
│   ├── mediapipe_backend.py
│   ├── u2netp_backend.py
│   └── yolo_onnx_backend.py
│
├── background/
│   ├── __init__.py
│   ├── composite.py
│   ├── generator.py
│   └── quality.py
│
├── agents/
│   ├── __init__.py
│   ├── aggregator.py     ← LLM: preference rule summarization (P8)
│   ├── critic.py         ← VLM: edit quality verification (P9)
│   ├── edit_flow.py
│   ├── planner.py        ← VLM: image + intent → HumanPlan
│   └── AGENTS.md
│
├── planner/
│   ├── __init__.py
│   └── compiler.py       ← deterministic HumanPlan → OpGraph
│
├── recipe/
│   ├── __init__.py
│   ├── renderer.py
│   ├── session.py
│   └── store.py
│
├── preferences/
│   ├── __init__.py
│   └── store.py
│
├── pipeline/
│   ├── __init__.py
│   ├── batch.py
│   ├── cost_router.py
│   ├── job_queue.py
│   └── plan_cache.py
│
├── templates/
│   ├── __init__.py
│   ├── framing.py
│   └── planner.py
│
└── app/
    ├── __init__.py
    ├── main.py
    ├── state.py
    ├── stubs.py
    └── components/
        ├── __init__.py
        ├── batch_review.py
        ├── candidate_picker.py
        ├── canvas.py
        ├── plan_view.py
        ├── prefs_panel.py
        ├── preview.py
        ├── settings.py
        └── upload.py

tests/
├── fixtures/
│   ├── face_portrait.jpg
│   ├── prompts/
│   │   └── base_prompt_full_mode.txt
│   └── schemas/
│       ├── sample_opgraph.json
│       ├── sample_plan.json
│       └── sample_recipe.json
├── unit/
│   ├── test_background.py
│   ├── test_edit_flow.py
│   ├── test_framing.py
│   ├── test_imageio.py
│   ├── test_op_catalog.py
│   ├── test_ops.py
│   ├── test_p9_critic.py
│   ├── test_p10_hardening.py
│   ├── test_p11_batch.py
│   ├── test_p13_character_focus.py
│   ├── test_planner.py
│   ├── test_prefs.py
│   ├── test_recipe.py
│   ├── test_schema.py
│   └── test_secrets.py
├── integration/
└── e2e/                          # live-browser Playwright tests (real API + real MediaPipe), see agent_notes/commands.md
    ├── conftest.py
    ├── _helpers.py
    └── test_full_edit_and_framing.py

.env.example
.gitignore
pyproject.toml
requirements.txt
requirements_dev.txt
```
