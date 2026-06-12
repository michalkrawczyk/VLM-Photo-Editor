"""View codebase structure from module_map.json in a format suited for LLM agents.

Default output: file paths only (minimal token footprint).
Use --include to progressively add detail.  Use --limit_module / --limit_file
to zoom into a specific part of the codebase.

Available --include values
--------------------------
  docstring   Module / class / method / function docstrings (first line only)
  classes     Class names
  bases       Class base classes  (implies --include classes)
  methods     Method names within each class  (implies --include classes)
  functions   Module-level function names
  signatures  Parameter lists and return annotations for functions/methods
  lines       Source line numbers for classes, methods and functions
  calls       Call-site list recorded per file (capped at 20)
  constants   UPPER_CASE module constants and __all__
  all         All of the above

Usage examples
--------------
    python agent_notes/view_module_map.py
    python agent_notes/view_module_map.py --include classes
    python agent_notes/view_module_map.py --include classes methods docstring
    python agent_notes/view_module_map.py --include all
    python agent_notes/view_module_map.py --limit_module ops
    python agent_notes/view_module_map.py --limit_file image_io.py
    python agent_notes/view_module_map.py --limit_module schema --include classes methods signatures
    python agent_notes/view_module_map.py --include classes --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INCLUDE_CHOICES = (
    "docstring",
    "classes",
    "bases",
    "methods",
    "functions",
    "signatures",
    "lines",
    "calls",
    "constants",
    "all",
)

_I = "  "  # indent unit
_CALLS_CAP = 20  # max call-sites shown per file in text mode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has(includes: set[str], *keys: str) -> bool:
    """Return True if 'all' or any of *keys* is in *includes*."""
    return "all" in includes or any(k in includes for k in keys)


def _sig_str(sig: dict) -> str:
    """Format a signature dict as ``(param: ann, ...) -> return``."""
    params = sig.get("params", [])
    parts: list[str] = []
    for p in params:
        ann = p.get("annotation")
        parts.append(f"{p['name']}: {ann}" if ann else p["name"])
    ret = sig.get("return_annotation")
    ret_part = f" -> {ret}" if ret else ""
    return f"({', '.join(parts)}){ret_part}"


def _normalize_includes(includes: set[str]) -> set[str]:
    """Apply implicit dependency rules and return the expanded set."""
    includes = set(includes)
    # methods / bases without classes is meaningless visually
    if _has(includes, "methods", "bases"):
        includes.add("classes")
    return includes


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_map(map_path: Path) -> list[dict]:
    """Load module_map.json from *map_path*."""
    if not map_path.exists():
        print(f"[ERROR] Module map not found: {map_path}", file=sys.stderr)
        sys.exit(1)
    with map_path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        print("[ERROR] module_map.json must be a JSON array.", file=sys.stderr)
        sys.exit(1)
    return data


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------


def _render_record_text(record: dict, includes: set[str]) -> list[str]:
    """Render a single module record as text lines."""
    lines: list[str] = []
    lines.append(record.get("path", "?"))

    if record.get("error"):
        lines.append(f"{_I}[ERROR] {record['error']}")
        return lines

    # module docstring
    if _has(includes, "docstring"):
        doc = record.get("module_docstring")
        if doc:
            first = doc.strip().splitlines()[0].strip()
            lines.append(f'{_I}"""  {first}')

    # classes
    if _has(includes, "classes"):
        for cls_name, cls_info in record.get("classes", {}).items():
            if not isinstance(cls_info, dict):
                continue

            # class header line
            base_part = ""
            if _has(includes, "bases") and cls_info.get("bases"):
                base_part = f"({', '.join(cls_info['bases'])})"
            line_part = (
                f"  :{cls_info['line']}" if _has(includes, "lines") and cls_info.get("line") else ""
            )
            lines.append(f"{_I}class {cls_name}{base_part}{line_part}")

            # class docstring
            if _has(includes, "docstring") and cls_info.get("docstring"):
                first = cls_info["docstring"].strip().splitlines()[0].strip()
                lines.append(f'{_I * 2}"""  {first}')

            # methods
            if _has(includes, "methods"):
                for m_name, m_info in cls_info.get("methods", {}).items():
                    sig_part = ""
                    line_tag = ""
                    doc_part = ""
                    if isinstance(m_info, dict):
                        if _has(includes, "signatures") and m_info.get("signature"):
                            sig_part = _sig_str(m_info["signature"])
                        if _has(includes, "lines") and m_info.get("line"):
                            line_tag = f"  :{m_info['line']}"
                        if _has(includes, "docstring") and m_info.get("docstring"):
                            first = m_info["docstring"].strip().splitlines()[0].strip()
                            doc_part = f'  # "{first}"'
                    lines.append(f"{_I * 2}def {m_name}{sig_part}{line_tag}{doc_part}")

    # module-level functions
    if _has(includes, "functions"):
        for fn_name, fn_info in record.get("functions", {}).items():
            sig_part = ""
            line_tag = ""
            doc_part = ""
            if isinstance(fn_info, dict):
                if _has(includes, "signatures") and fn_info.get("signature"):
                    sig_part = _sig_str(fn_info["signature"])
                if _has(includes, "lines") and fn_info.get("line"):
                    line_tag = f"  :{fn_info['line']}"
                if _has(includes, "docstring") and fn_info.get("docstring"):
                    first = fn_info["docstring"].strip().splitlines()[0].strip()
                    doc_part = f'  # "{first}"'
            lines.append(f"{_I}def {fn_name}{sig_part}{line_tag}{doc_part}")

    # constants
    if _has(includes, "constants"):
        consts = record.get("constants", {})
        mod_consts = consts.get("module_constants", [])
        all_list = consts.get("__all__")
        if mod_consts:
            lines.append(f"{_I}constants: {', '.join(mod_consts)}")
        if all_list is not None:
            lines.append(f"{_I}__all__: {', '.join(all_list)}")

    # calls
    if _has(includes, "calls"):
        calls = record.get("calls", [])
        if calls:
            call_strs: list[str] = []
            for c in calls[:_CALLS_CAP]:
                recv = c.get("receiver")
                name = c.get("name", "?")
                lnum = c.get("line")
                call_strs.append(f"{recv}.{name}:{lnum}" if recv else f"{name}:{lnum}")
            lines.append(f"{_I}calls: {', '.join(call_strs)}")
            if len(calls) > _CALLS_CAP:
                lines.append(f"{_I}  ... (+{len(calls) - _CALLS_CAP} more)")

    return lines


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


def _prune_record_json(record: dict, includes: set[str]) -> dict:
    """Return a pruned copy of *record* containing only the requested fields."""
    out: dict = {
        "path": record.get("path"),
        "file": record.get("file"),
    }

    if record.get("error"):
        out["error"] = record["error"]
        return out

    if _has(includes, "docstring"):
        out["module_docstring"] = record.get("module_docstring")

    if _has(includes, "classes"):
        pruned_classes: dict = {}
        for cls_name, cls_info in record.get("classes", {}).items():
            if not isinstance(cls_info, dict):
                continue
            cls_entry: dict = {}
            if _has(includes, "docstring"):
                cls_entry["docstring"] = cls_info.get("docstring")
            if _has(includes, "bases"):
                cls_entry["bases"] = cls_info.get("bases", [])
            if _has(includes, "lines"):
                cls_entry["line"] = cls_info.get("line")
            if _has(includes, "methods"):
                pruned_methods: dict = {}
                for m_name, m_info in cls_info.get("methods", {}).items():
                    m_entry: dict = {}
                    if isinstance(m_info, dict):
                        if _has(includes, "docstring"):
                            m_entry["docstring"] = m_info.get("docstring")
                        if _has(includes, "signatures"):
                            m_entry["signature"] = m_info.get("signature")
                        if _has(includes, "lines"):
                            m_entry["line"] = m_info.get("line")
                    pruned_methods[m_name] = m_entry if m_entry else None
                cls_entry["methods"] = pruned_methods
            pruned_classes[cls_name] = cls_entry
        out["classes"] = pruned_classes

    if _has(includes, "functions"):
        pruned_fns: dict = {}
        for fn_name, fn_info in record.get("functions", {}).items():
            fn_entry: dict = {}
            if isinstance(fn_info, dict):
                if _has(includes, "docstring"):
                    fn_entry["docstring"] = fn_info.get("docstring")
                if _has(includes, "signatures"):
                    fn_entry["signature"] = fn_info.get("signature")
                if _has(includes, "lines"):
                    fn_entry["line"] = fn_info.get("line")
            pruned_fns[fn_name] = fn_entry if fn_entry else None
        out["functions"] = pruned_fns

    if _has(includes, "constants"):
        out["constants"] = record.get("constants", {})

    if _has(includes, "calls"):
        out["calls"] = record.get("calls", [])

    return out


# ---------------------------------------------------------------------------
# Main view logic
# ---------------------------------------------------------------------------


def view(
    module_map: list[dict],
    includes: set[str],
    limit_module: str | None = None,
    limit_file: str | None = None,
    output_json: bool = False,
) -> str:
    """Return a formatted string of *module_map* filtered by the supplied options.

    Parameters
    ----------
    module_map:
        Loaded list of module records from module_map.json.
    includes:
        Set of field names to include beyond path/file.  Pass ``{'all'}`` for
        everything.  Implicit dependency rules are applied automatically.
    limit_module:
        If set, only records whose ``parent_module`` matches (case-insensitive).
    limit_file:
        If set, only records whose ``file`` or ``module`` (stem) matches.
    output_json:
        Emit pruned JSON instead of text tree.
    """
    includes = _normalize_includes(includes)
    records = list(module_map)

    if limit_module:
        lm = limit_module.lower()
        records = [r for r in records if r.get("parent_module", "").lower() == lm]

    if limit_file:
        lf = limit_file.lower()
        # Match against filename (with or without .py) and module stem
        records = [
            r
            for r in records
            if r.get("file", "").lower() == lf
            or r.get("file", "").lower() == lf + ".py"
            or r.get("module", "").lower() == lf
        ]

    if not records:
        return "No entries match the given filters."

    if output_json:
        pruned = [_prune_record_json(r, includes) for r in records]
        return json.dumps(pruned, indent=2, ensure_ascii=False)

    # text output — one block per file, blank line between blocks
    blocks: list[str] = []
    for record in records:
        block_lines = _render_record_text(record, includes)
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="view_module_map",
        description=(
            "View codebase structure from module_map.json suited for LLM agents.\n"
            "Default output: file paths only.  Use --include to add detail."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
--include choices
-----------------
  docstring   First line of module / class / method / function docstrings
  classes     Class names
  bases       Class base classes  (implies classes)
  methods     Method names within classes  (implies classes)
  functions   Module-level function names
  signatures  Parameter lists + return annotations
  lines       Source line numbers
  calls       Call-sites per file (capped at 20)
  constants   UPPER_CASE constants and __all__
  all         Everything above

Examples
--------
  python agent_notes/view_module_map.py
  python agent_notes/view_module_map.py --include classes
  python agent_notes/view_module_map.py --include classes methods
  python agent_notes/view_module_map.py --include all --limit_module ops
  python agent_notes/view_module_map.py --limit_file image_io --include classes methods docstring signatures
  python agent_notes/view_module_map.py --include classes methods --json
""",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        choices=list(_INCLUDE_CHOICES),
        metavar="FIELD",
        default=[],
        help=("Fields to include beyond path/file. " "Choices: " + ", ".join(_INCLUDE_CHOICES)),
    )
    parser.add_argument(
        "--limit_module",
        metavar="MODULE",
        default=None,
        help=(
            "Show only files whose immediate parent directory matches MODULE "
            "(e.g. agents, tests)."
        ),
    )
    parser.add_argument(
        "--limit_file",
        metavar="FILE",
        default=None,
        help=(
            "Show only the file matching FILE.  Accepts filename (with or without "
            ".py) or module stem."
        ),
    )
    parser.add_argument(
        "--map",
        default=None,
        metavar="PATH",
        help=(
            "Path to module_map.json " "(default: agent_ignore/module_map.json in project root)."
        ),
    )
    parser.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Emit filtered JSON instead of text tree.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the view-module-map CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.map:
        map_path = Path(args.map).expanduser().resolve()
    else:
        map_path = Path(__file__).parent.parent / "agent_ignore" / "module_map.json"

    module_map = load_map(map_path)

    print(
        view(
            module_map=module_map,
            includes=set(args.include),
            limit_module=args.limit_module,
            limit_file=args.limit_file,
            output_json=args.output_json,
        )
    )


if __name__ == "__main__":
    main()