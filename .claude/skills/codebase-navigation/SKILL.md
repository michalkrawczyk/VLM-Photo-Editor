---
name: codebase-navigation
description: "Use when locating classes, methods, or functions; exploring subsystem structure; finding call sites; reading signatures; or understanding file organization. ALWAYS run module_map scripts BEFORE grep_search or semantic_search."
---

# Codebase Navigation — Module Map Tools

**BLOCKING RULE:** Run module_map scripts before any `grep_search` or `semantic_search` call.
No project dependencies needed — tools work directly from `agent_ignore/module_map.json`.

---

## 0. Setup — `generate_module_map.py`

Re-run after adding, removing, or renaming files.

| Argument | Default | Purpose |
|----------|---------|---------|
| `--root PATH` | project root | Root directory for path resolution |
| `--dirs DIR [DIR …]` | `vlm_photo_editor tests` | Directories to scan (relative to `--root`) |
| `--output PATH` | `agent_ignore/module_map.json` | Output JSON file |

```bash
python agent_notes/generate_module_map.py
python agent_notes/generate_module_map.py --dirs vlm_photo_editor tests
```

---

## 1. Search — `search_module_map.py`

Find symbols by name. **Start here for any "where is X?" question.**

| Argument | Values / Default | Purpose |
|----------|-----------------|---------|
| `query` *(positional)* | string | Case-insensitive substring (or exact with `--exact`) |
| `--type` | `all` · `module` · `class` · `method` · `function` · `usage` · `param` — default `all` | Restrict to a symbol kind |
| `--package PACKAGE` | e.g. `vlm_photo_editor` | Filter by top-level package directory |
| `--parent PARENT` | e.g. `ops` | Filter by immediate parent directory |
| `--map PATH` | `agent_ignore/module_map.json` | Custom map file location |
| `--exact` | flag | Exact match instead of substring |
| `--no-docstrings` | flag | Suppress docstrings in output |
| `--no-methods` | flag | Suppress method listings inside class results |
| `--no-functions` | flag | Suppress module-level function results |
| `--json` | flag | Emit results as JSON |

```bash
python agent_notes/search_module_map.py ImageOp                                # all symbols containing "ImageOp"
python agent_notes/search_module_map.py HumanPlan --type class
python agent_notes/search_module_map.py apply --type method --parent ops
python agent_notes/search_module_map.py plan --type function --package vlm_photo_editor
python agent_notes/search_module_map.py compile --type usage                   # call sites
python agent_notes/search_module_map.py Recipe --type param
python agent_notes/search_module_map.py OpGraph --json
python agent_notes/search_module_map.py execute --exact --type function
```

---

## 2. Browse — `view_module_map.py`

Explore file/module structure. **Start here for subsystem overviews.**

| Argument | Values / Default | Purpose |
|----------|-----------------|---------|
| `--include FIELD [FIELD …]` | see table below — default none (paths only) | Fields to display |
| `--limit_module MODULE` | e.g. `ops` | Show only files whose immediate parent dir matches |
| `--limit_file FILE` | e.g. `image_io` | Show only the named file (stem, with or without `.py`) |
| `--map PATH` | `agent_ignore/module_map.json` | Custom map file location |
| `--json` | flag | Emit filtered JSON instead of text tree |

**`--include` values:**

| Value | What it adds |
|-------|-------------|
| `classes` | Class names |
| `bases` | Base classes (implies `classes`) |
| `methods` | Method names per class (implies `classes`) |
| `functions` | Module-level function names |
| `signatures` | Parameter lists + return annotations |
| `lines` | Source line numbers for classes/methods/functions |
| `docstring` | First line of docstrings for modules/classes/methods |
| `calls` | Call sites recorded per file (capped at 20) |
| `constants` | `UPPER_CASE` constants and `__all__` |
| `all` | All of the above |

```bash
python agent_notes/view_module_map.py                                          # paths only
python agent_notes/view_module_map.py --limit_module ops --include classes methods
python agent_notes/view_module_map.py --include classes methods docstring
python agent_notes/view_module_map.py --limit_file image_io --include methods signatures lines
python agent_notes/view_module_map.py --include all
```

---

## Decision Table

| Situation | Command |
|-----------|---------|
| Locate a class | `search_module_map.py ClassName --type class` |
| Locate a method | `search_module_map.py method_name --type method` |
| All callers of a function | `search_module_map.py func_name --type usage` |
| Subsystem overview | `view_module_map.py --limit_module schema --include classes` |
| Read signatures before opening files | `view_module_map.py --limit_file filename --include methods signatures` |
| Full planning dump | `view_module_map.py --include all` |
| Which file defines a constant | `search_module_map.py CONSTANT_NAME --type module` |
| Methods on a class | `search_module_map.py ClassName --type class` (methods listed in result) |
