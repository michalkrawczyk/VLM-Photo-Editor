# Module Map

Three scripts over one generated index. No `.md` map file — the index is `agent_ignore/module_map.json` (gitignored, regenerate locally; AST-based, no imports needed).

**Always generate/view/search before grep or semantic search** for locating classes, methods, functions; exploring subsystem structure; finding call sites; reading signatures; understanding file organization.

## Generate — `agent_notes/utility_scripts/generate_module_map.py`

Scans `vlm_photo_editor/` and `tests/` by default, writes JSON (per-file module docstring, classes/methods/signatures/docstrings, top-level functions, call sites, module-level constants) to `agent_ignore/module_map.json`.

```
python agent_notes/utility_scripts/generate_module_map.py
python agent_notes/utility_scripts/generate_module_map.py --root /path/to/project
python agent_notes/utility_scripts/generate_module_map.py --dirs vlm_photo_editor tests
python agent_notes/utility_scripts/generate_module_map.py --output agent_ignore/custom_map.json
```

Also supports raw Python filtering against the loaded JSON directly (see the script's module docstring), e.g. `[e for e in data if e["parent_module"] == "ops"]`.

## View — `agent_notes/utility_scripts/view_module_map.py`

Formats the map for reading. File-paths-only by default.

```
python agent_notes/utility_scripts/view_module_map.py
python agent_notes/utility_scripts/view_module_map.py --include classes
python agent_notes/utility_scripts/view_module_map.py --include classes methods docstring
python agent_notes/utility_scripts/view_module_map.py --include all
python agent_notes/utility_scripts/view_module_map.py --limit_module ops
python agent_notes/utility_scripts/view_module_map.py --limit_file image_io.py
python agent_notes/utility_scripts/view_module_map.py --limit_module schema --include classes methods signatures
python agent_notes/utility_scripts/view_module_map.py --include classes --json
```

`--include` values: `docstring`, `classes`, `bases` (implies classes), `methods` (implies classes), `functions`, `signatures`, `lines`, `calls`, `constants`, `all`.

## Search — `agent_notes/utility_scripts/search_module_map.py`

```
python agent_notes/utility_scripts/search_module_map.py ImageOp --type class
python agent_notes/utility_scripts/search_module_map.py apply --type method --package vlm_photo_editor
python agent_notes/utility_scripts/search_module_map.py "plan" --no-methods --no-functions
python agent_notes/utility_scripts/search_module_map.py op --parent ops --json
```

`--type` choices: `all`, `module`, `class`, `method`, `function`, `usage`, `param`.

## Regeneration

Not automatic mid-task. `agent_notes/utility_scripts/cleanup.sh` regenerates it at end-of-session (after `black`/`isort`). If the map is stale mid-task, regenerate manually or fall back to grep and flag it.
