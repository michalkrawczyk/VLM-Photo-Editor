"""Generate a JSON map of modules -> classes/functions with their docstrings.

Scans specified directories (default: vlm_photo_editor/, tests/) using AST parsing
(no imports required, works without project dependencies installed).

Output format: list of objects, each representing one .py file.

Usage
-----
    python agent_notes/generate_module_map.py
    python agent_notes/generate_module_map.py --root /path/to/project
    python agent_notes/generate_module_map.py --dirs vlm_photo_editor tests
    python agent_notes/generate_module_map.py --output agent_ignore/custom_map.json

Filtering examples (Python)
---------------------------
    import json
    data = json.load(open("agent_ignore/module_map.json"))

    # All entries from the 'ops' submodule:
    [e for e in data if e["parent_module"] == "ops"]

    # A specific module by name:
    next(e for e in data if e["module"] == "image_io")

    # Only production code (no tests):
    [e for e in data if e["package"] == "vlm_photo_editor"]

    # Modules containing a specific class:
    [e for e in data if "ImageOp" in e.get("classes", {})]

    # All files with a missing module docstring:
    [e for e in data if e["module_docstring"] is None and "error" not in e]
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

DEFAULT_SCAN_DIRS = ["vlm_photo_editor", "tests"]

# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _extract_signature(
    func_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict:
    """Extract parameter list, return annotation and decorators from a function node.

    Parameters
    ----------
    func_node : ast.FunctionDef | ast.AsyncFunctionDef
        The AST node representing the function or method.

    Returns
    -------
    dict
        Keys:
        - ``params``: list of ``{"name": str, "annotation": str | None}``
        - ``return_annotation``: ``ast.unparse`` result or ``None``
        - ``decorators``: list of decorator name strings
    """
    params: list[dict] = []
    for arg in func_node.args.args:
        annotation = ast.unparse(arg.annotation) if arg.annotation else None
        params.append({"name": arg.arg, "annotation": annotation})

    return_annotation = ast.unparse(func_node.returns) if func_node.returns else None

    decorators: list[str] = []
    for dec in func_node.decorator_list:
        if isinstance(dec, ast.Name):
            decorators.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            decorators.append(dec.attr)
        else:
            try:
                decorators.append(ast.unparse(dec))
            except Exception:  # noqa: BLE001
                pass

    return {
        "params": params,
        "return_annotation": return_annotation,
        "decorators": decorators,
    }


def _extract_methods(class_node: ast.ClassDef) -> dict[str, dict]:
    """Extract method names, docstrings, signatures and line numbers from a class.

    Parameters
    ----------
    class_node : ast.ClassDef
        The AST node representing the class.

    Returns
    -------
    dict[str, dict]
        Mapping of method name -> ``{"docstring": str|None, "signature": dict,
        "line": int}``.
    """
    methods: dict[str, dict] = {}
    for node in ast.iter_child_nodes(class_node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[node.name] = {
                "docstring": ast.get_docstring(node),
                "signature": _extract_signature(node),
                "line": node.lineno,
            }
    return methods


# Node types at module level that may wrap class/function definitions
# (e.g. try/except for optional imports, if TYPE_CHECKING blocks, etc.)
# ast.TryStar (except*) is Python 3.11+; guard against older runtimes
_WRAPPER_TYPES = tuple(
    t
    for t in [ast.Try, getattr(ast, "TryStar", None), ast.If, ast.With, ast.AsyncWith]
    if t is not None
)


def _iter_module_level_defs(
    parent: ast.AST,
) -> list[ast.stmt]:
    """Yield direct class/function definitions, descending into wrapper blocks.

    Wrapper blocks (Try, If, With) at module or wrapper level are entered
    recursively, so that definitions inside ``try/except ImportError`` guards
    or ``if TYPE_CHECKING:`` blocks are not missed.

    Parameters
    ----------
    parent : ast.AST
        A module node or a wrapper block node.

    Returns
    -------
    list[ast.stmt]
        Flat list of ClassDef / FunctionDef / AsyncFunctionDef nodes.
    """
    result: list[ast.stmt] = []
    children: list[ast.stmt] = list(ast.iter_child_nodes(parent))  # type: ignore[arg-type]
    for node in children:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(node)
        elif isinstance(node, _WRAPPER_TYPES):
            # Recurse into all child statement lists (body, handlers, orelse, finalbody)
            result.extend(_iter_module_level_defs(node))
    return result


def _extract_top_level_functions(
    module_node: ast.Module,
) -> dict[str, dict]:
    """Extract top-level function names, docstrings, signatures and line numbers.

    Descends into wrapper blocks (Try, If, With) to capture functions defined
    inside optional-import guards.

    Parameters
    ----------
    module_node : ast.Module
        The parsed AST of the module.

    Returns
    -------
    dict[str, dict]
        Mapping of function name -> ``{"docstring": str|None, "signature": dict,
        "line": int}``.
    """
    functions: dict[str, dict] = {}
    for node in _iter_module_level_defs(module_node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions[node.name] = {
                "docstring": ast.get_docstring(node),
                "signature": _extract_signature(node),
                "line": node.lineno,
            }
    return functions


def _extract_classes(module_node: ast.Module) -> dict[str, dict]:
    """Extract class names, their docstrings, and methods from a module AST.

    Descends into wrapper blocks (Try, If, With) to capture classes defined
    inside optional-import guards.

    Parameters
    ----------
    module_node : ast.Module
        The parsed AST of the module.

    Returns
    -------
    dict[str, dict]
        Mapping of class name -> {"docstring": ..., "methods": {...}}.
    """
    classes: dict[str, dict] = {}
    for node in _iter_module_level_defs(module_node):
        if isinstance(node, ast.ClassDef):
            classes[node.name] = {
                "docstring": ast.get_docstring(node),
                "bases": [ast.unparse(b) for b in node.bases],
                "line": node.lineno,
                "methods": _extract_methods(node),
            }
    return classes


def _extract_calls(tree: ast.AST) -> list[dict]:
    """Extract all function/method call sites from an AST tree.

    Uses ``ast.walk`` so nested calls (e.g. inside comprehensions or lambdas)
    are included.

    Parameters
    ----------
    tree : ast.AST
        Parsed AST of the module.

    Returns
    -------
    list[dict]
        Each element has keys:
        - ``name``: callee name (attribute name or bare name)
        - ``receiver``: variable name before the dot, or ``None``
        - ``line``: source line number
    """
    calls: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            calls.append({"name": func.id, "receiver": None, "line": node.lineno})
        elif isinstance(func, ast.Attribute):
            receiver = func.value.id if isinstance(func.value, ast.Name) else None
            calls.append({"name": func.attr, "receiver": receiver, "line": node.lineno})
    return calls


def _extract_constants(tree: ast.Module) -> dict:
    """Extract module-level UPPER_CASE constants and ``__all__`` from an AST.

    Only direct module-level ``ast.Assign`` nodes are scanned (no wrapper
    blocks), which matches typical constant declaration style.

    Parameters
    ----------
    tree : ast.Module
        Parsed AST of the module.

    Returns
    -------
    dict
        Keys:
        - ``module_constants``: list of ``UPPER_CASE`` variable names
        - ``__all__``: list of exported names, or ``None`` if absent
    """
    upper_case: list[str] = []
    all_list: list[str] | None = None

    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name == "__all__" and isinstance(node.value, ast.List):
                all_list = [
                    (
                        elt.value
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                        else ast.unparse(elt)
                    )
                    for elt in node.value.elts
                ]
            elif name.isupper() and name != "__all__":
                upper_case.append(name)

    return {"module_constants": upper_case, "__all__": all_list}


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def _build_metadata(rel_path: Path, root: Path) -> dict:
    """Build searchable metadata fields from a file's relative path.

    Parameters
    ----------
    rel_path : Path
        Path of the file relative to the project root.
    root : Path
        Absolute path of the project root (unused here, kept for symmetry).

    Returns
    -------
    dict
        Fields: path, file, module, parent_module, package.
    """
    parts = rel_path.parts  # e.g. ('vlm_photo_editor', 'ops', 'image_io.py')
    return {
        "path": str(rel_path),
        "file": rel_path.name,
        "module": rel_path.stem,
        "parent_module": rel_path.parent.name,  # immediate parent dir
        "package": parts[0],  # top-level scan dir (core / tests)
    }


def process_file(abs_path: Path, rel_path: Path) -> dict:
    """Parse a single Python file and extract its structure.

    Parameters
    ----------
    abs_path : Path
        Absolute path to the Python file.
    rel_path : Path
        Path relative to the project root (used as the record identifier).

    Returns
    -------
    dict
        Record with metadata + module_docstring, classes, functions —
        or an error entry if the file cannot be parsed.
    """
    entry = _build_metadata(rel_path, abs_path.parent)

    try:
        source = abs_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError as exc:
        LOGGER.warning("SyntaxError in %s: %s", rel_path, exc)
        entry["error"] = f"SyntaxError: {exc}"
        return entry
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Cannot read %s: %s", rel_path, exc)
        entry["error"] = str(exc)
        return entry

    entry["module_docstring"] = ast.get_docstring(tree)
    entry["classes"] = _extract_classes(tree)
    entry["functions"] = _extract_top_level_functions(tree)
    entry["calls"] = _extract_calls(tree)
    entry["constants"] = _extract_constants(tree)
    return entry


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------


def scan_directories(root: Path, dirs: list[str]) -> list[dict]:
    """Scan the specified directories for Python files and extract their structure.

    Parameters
    ----------
    root : Path
        Absolute path of the project root.
    dirs : list[str]
        Directory names (relative to root) to scan.

    Returns
    -------
    list[dict]
        List of module records, one per .py file found.
    """
    records: list[dict] = []
    for dir_name in dirs:
        scan_root = root / dir_name
        if not scan_root.exists():
            LOGGER.warning("Directory not found, skipping: %s", scan_root)
            continue

        py_files = sorted(scan_root.rglob("*.py"))
        for abs_path in py_files:
            # Skip __pycache__ directories
            if "__pycache__" in abs_path.parts:
                continue
            rel_path = abs_path.relative_to(root)
            records.append(process_file(abs_path, rel_path))

    return records


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Parameters
    ----------
    argv : list[str] | None
        Argument list (defaults to sys.argv[1:]).

    Returns
    -------
    argparse.Namespace
        Parsed arguments.
    """
    script_dir = Path(__file__).parent
    default_root = script_dir.parent
    default_output = default_root / "agent_ignore" / "module_map.json"

    parser = argparse.ArgumentParser(
        description="Generate a JSON map of modules -> classes/functions/docstrings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=default_root,
        help=f"Project root directory (default: {default_root})",
    )
    parser.add_argument(
        "--dirs",
        nargs="+",
        default=DEFAULT_SCAN_DIRS,
        metavar="DIR",
        help=f"Directories to scan, relative to --root (default: {DEFAULT_SCAN_DIRS})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Output JSON file path (default: {default_output})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Run the module map generation.

    Parameters
    ----------
    argv : list[str] | None
        Optional argument list for programmatic invocation.
    """
    args = parse_args(argv)
    root: Path = args.root.resolve()

    LOGGER.info("Project root : %s", root)
    LOGGER.info("Scanning     : %s", args.dirs)
    LOGGER.info("Output       : %s", args.output)

    records = scan_directories(root, args.dirs)

    errors = [r for r in records if "error" in r]
    ok = len(records) - len(errors)

    # Write output
    output_path: Path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)

    LOGGER.info(
        "Done — processed %d file(s), %d error(s) → %s",
        ok,
        len(errors),
        output_path,
    )
    if errors:
        for e in errors:
            LOGGER.warning("  ! %s: %s", e["path"], e.get("error"))


if __name__ == "__main__":
    main()
