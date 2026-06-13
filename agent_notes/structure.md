# Project File Structure

Modules: `config` · `secrets` · `schema` · `imageio` · `models` · `ops` · `framing` · `background` · `agents` · `planner` · `recipe` · `prefs` · `ps_bridge` · `app`

For per-module invariants, import rules, and common mistakes see `AGENTS.md` in each module directory.

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
│   ├── executor.py
│   ├── validator.py
│   ├── mask.py
│   └── backends/
│       ├── __init__.py
│       ├── pil_backend.py
│       ├── cv_backend.py
│       └── stubs.py
│
├── framing/
│   ├── __init__.py
│   ├── detector.py
│   └── modes.py
│
├── background/
│   ├── __init__.py
│   ├── generator.py
│   ├── composite.py
│   └── quality.py
│
├── agents/
│   ├── __init__.py
│   ├── planner.py        ← VLM: image + intent → HumanPlan
│   ├── critic.py         ← VLM: edit quality verification (P9)
│   ├── aggregator.py     ← LLM: preference rule summarization (P8)
│   └── AGENTS.md
│
├── planner/
│   ├── __init__.py
│   └── compiler.py       ← deterministic HumanPlan → OpGraph
│
├── recipe/
│   ├── __init__.py
│   ├── store.py
│   └── renderer.py
│
├── prefs/
│   ├── __init__.py
│   ├── explicit.py
│   └── learned.py
│
├── ps_bridge/
│   ├── __init__.py
│   ├── client.py
│   └── vocabulary.py
│
└── app/
    ├── __init__.py
    ├── main.py
    ├── state.py
    ├── stubs.py
    └── components/
        ├── __init__.py
        ├── upload.py
        ├── preview.py
        ├── plan_view.py
        ├── canvas.py
        ├── prefs_panel.py
        └── settings.py

tests/
├── fixtures/
│   ├── images/
│   │   ├── sample.jpg
│   │   ├── sample.png
│   │   └── sample.nef
│   └── schemas/
│       ├── sample_plan.json
│       ├── sample_opgraph.json
│       └── sample_recipe.json
├── unit/
│   ├── test_schema.py
│   ├── test_secrets.py
│   ├── test_imageio.py
│   ├── test_ops.py
│   ├── test_recipe.py
│   ├── test_planner.py
│   ├── test_framing.py
│   └── test_background.py
└── integration/
    └── test_pipeline.py

.env.example
.gitignore
pyproject.toml
requirements.txt
requirements_dev.txt
```
