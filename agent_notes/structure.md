# Project File Structure

Derived from the module map in `photo_editor_build_plan.md`:
`config` · `secrets` · `schema` · `imageio` · `models` · `ops` · `framing` · `background` · `planner` · `critic` · `recipe` · `prefs` · `ps_bridge` · `app`

---

```
vlm_photo_editor/
│
├── config/                         # P0 — policy modes, model registry, thresholds
│   ├── __init__.py
│   ├── policy.py                   # PolicyMode enum (Auto / PS-strict / No-PS), risk-tier gating rules
│   ├── registry.py                 # role→model mapping; switchable at runtime
│   └── settings.py                 # app-level paths, seam-quality threshold, cache TTL
│
├── secrets/                        # P0 — secret resolution and redaction
│   ├── __init__.py
│   ├── store.py                    # SecretStore.get(provider): env → keyring → .env precedence
│   └── redaction.py                # log/error filter that scrubs key-shaped strings
│
├── schema/                         # P0 — all Pydantic contracts; imported by every other module
│   ├── __init__.py
│   ├── ops.py                      # Op, OpGraph, OpName enum, Backend enum, RiskTier enum
│   ├── plan.py                     # HumanPlan, HumanStep (stable step-IDs), CompilerResult
│   ├── recipe.py                   # Recipe: op-graph + model + prompt + seed per genAI op
│   └── prefs.py                    # Preferences, ExplicitRule, LearnedRule, PrefsVersion
│
├── imageio/                        # P1 — image I/O; never writes over source
│   ├── __init__.py
│   ├── container.py                # ImageContainer: pixels, bit-depth, ICC profile, metadata
│   ├── loaders.py                  # RAW (rawpy → 16-bit linear), JPG/PNG (Pillow); format detection
│   └── savers.py                   # save(): raises if dest == source path; naming scheme
│
├── models/                         # P0/P4 — VLM client factories
│   ├── __init__.py
│   └── registry.py                 # build_client(role) → anthropic.Anthropic or compatible client
│
├── ops/                            # P2 — deterministic edit engine
│   ├── __init__.py
│   ├── executor.py                 # Executor.apply(container, opgraph) → ImageContainer
│   ├── validator.py                # reject unknown ops, out-of-bounds params; clear error messages
│   ├── mask.py                     # bounding-box → region mask; subject-pixel freeze assertion
│   └── backends/
│       ├── __init__.py
│       ├── pil_backend.py          # crop, rotate, white-balance, exposure, denoise via Pillow
│       ├── cv_backend.py           # ops that benefit from OpenCV (e.g. bilateral denoise)
│       └── stubs.py                # genAI and Photoshop backend stubs (raise NotImplementedError)
│
├── framing/                        # P5 — subject-aware composition
│   ├── __init__.py
│   ├── detector.py                 # face detection + saliency map → subject bbox
│   └── modes.py                    # FramingMode enum implementations:
│                                   #   rule_of_thirds, golden_ratio, golden_spiral,
│                                   #   center_symmetry, portrait_headroom, face_only,
│                                   #   negative_space, fill_frame, lead_room, horizon_third
│
├── background/                     # P6 — genAI background pipeline
│   ├── __init__.py
│   ├── generator.py                # generate N candidates (seed, prompt, model stored for recipe)
│   ├── composite.py                # LAB color transfer, grain/noise match, feathered seam blend
│   └── quality.py                  # seam metric gate; seed re-roll; flag-for-manual fallback
│
├── planner/                        # P4 — two-stage VLM planning
│   ├── __init__.py
│   ├── planner.py                  # VLM call → HumanPlan (numbered steps with "why" per step)
│   └── compiler.py                 # HumanPlan → OpGraph; step-ID linkage; allowed-op enforcement
│
├── critic/                         # P9 — optional quality-gate VLM
│   ├── __init__.py
│   └── critic.py                   # verify result vs intent; loop on failure
│
├── recipe/                         # P3 — non-destructive store and replay
│   ├── __init__.py
│   ├── store.py                    # serialize/deserialize to <name>.edit.json sidecar; XMP stub
│   └── renderer.py                 # deterministic render(); undo/redo stack; variant branches
│
├── prefs/                          # P8 — preferences learning loop
│   ├── __init__.py
│   ├── explicit.py                 # user-authored rules; always override learned on conflict
│   └── learned.py                  # delta capture on accept/reject/edit; LLM aggregation;
│                                   # candidate rules → user approval → inject into planner
│
├── ps_bridge/                      # P9 — optional Photoshop integration
│   ├── __init__.py
│   ├── client.py                   # MCP server wrapping UXP/ExtendScript; capability discovery
│   └── vocabulary.py               # PS-expressible op set fed into planner prompt for PS-strict mode
│
└── app/                            # P0.5 / P7 — Streamlit UI
    ├── __init__.py
    ├── main.py                     # entrypoint: `streamlit run app/main.py`
    ├── state.py                    # session state management; no secrets in state
    ├── stubs.py                    # mock data for P0.5 shell (replaced by real wiring in P7)
    └── components/
        ├── __init__.py
        ├── upload.py               # file upload widget
        ├── preview.py              # before/after side-by-side preview
        ├── plan_view.py            # plan display; expandable compiled ops per step
        ├── canvas.py               # streamlit-drawable-canvas bbox selection
        ├── prefs_panel.py          # explicit + learned rules panel; per-rule toggles
        └── settings.py             # masked API-key entry; role→model switchers; mode buttons

tests/
├── fixtures/
│   ├── images/
│   │   ├── sample.jpg
│   │   ├── sample.png
│   │   └── sample.nef              # RAW fixture (or .cr2)
│   └── schemas/
│       ├── sample_plan.json
│       ├── sample_opgraph.json
│       └── sample_recipe.json
├── unit/
│   ├── test_schema.py              # schema validation against fixtures
│   ├── test_secrets.py             # SecretStore + redaction filter
│   ├── test_imageio.py             # round-trip per format; RAW bit-depth; source-override guard
│   ├── test_ops.py                 # op execution, validator rejection, bbox region isolation
│   ├── test_recipe.py              # deterministic render; undo; preset reapply
│   ├── test_planner.py             # plan→opgraph; step-ID linkage; allowed-op enforcement
│   ├── test_framing.py             # each mode on face + scene fixtures; no head-clipping
│   └── test_background.py          # subject pixels frozen; seam gate; N candidates
└── integration/
    └── test_pipeline.py            # end-to-end: upload → plan → compile → execute → recipe

.env.example                        # documents required env vars; no real values
.gitignore                          # includes .env, *.edit.json is NOT ignored (sidecars ship)
pyproject.toml                      # project metadata, tool config (black, ruff, mypy, pytest)
requirements.txt
requirements_dev.txt
```

---

## Notes

- `schema/` must have **zero imports from sibling modules** — it is the root dependency.
- `secrets/redaction.py` is wired into the root logger at startup in `app/main.py` so all log sinks are covered before any key ever flows through the system.
- `app/stubs.py` provides the complete mock surface for P0.5. Every component in `app/components/` accepts an optional `data` parameter; when it is a stub type, no real processing is triggered.
- `ops/backends/stubs.py` keeps the genAI and Photoshop backends cleanly removable — import only under the active policy.
- XMP sidecar in `recipe/store.py` is a stub at P3; full XMP round-trip is deferred to P10 hardening.
