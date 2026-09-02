#!/usr/bin/env python3
"""Validate the agent_notes/ bundle against what is actually on disk.

This bundle deliberately carries no YAML frontmatter (see the closing note in
``agent_notes/index.md``), so this validator checks what the bundle does promise instead:

1. links      every markdown link in a bundle file resolves to an existing path
2. index      every bundle file has a row in ``index.md``
3. orphans    every path named in an ``index.md`` row exists on disk
4. pointers   every backticked ``agent_notes/...`` path in CLAUDE.md exists on disk

Check 4 matters because CLAUDE.md names most bundle files in prose backticks rather than
markdown links; a link-only check would miss exactly the drift ``insights.md`` documents.

Usage:
    python3 agent_notes/utility_scripts/validate_okf.py
    python3 agent_notes/utility_scripts/validate_okf.py agent_notes
    python3 agent_notes/utility_scripts/validate_okf.py agent_notes --extra CLAUDE.md
    python3 agent_notes/utility_scripts/validate_okf.py --quiet

Exit 0 if every check passed, 1 if any failed, 2 on bad usage.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
INDEX_ROW_RE = re.compile(r"^\|\s*`([^`]+)`")
BUNDLE_POINTER_RE = re.compile(r"`(agent_notes/[^`]+)`")

SKIP_LINK_PREFIXES = ("http://", "https://", "mailto:", "#")
TRACKED_SUFFIXES = (".md", ".py", ".sh")

QUIET = False


def note(message: str) -> None:
    """Print a progress line unless running in quiet mode.

    Args:
        message: Line to print.
    """
    if not QUIET:
        print(message)


def iter_markdown(bundle: Path) -> list[Path]:
    """Return every markdown file in the bundle, sorted.

    Args:
        bundle: Bundle directory to scan.

    Returns:
        Sorted list of ``*.md`` paths.
    """
    return sorted(p for p in bundle.rglob("*.md") if "__pycache__" not in p.parts)


def tracked_files(bundle: Path) -> list[Path]:
    """Return every bundle file that ``index.md`` is expected to list.

    Args:
        bundle: Bundle directory to scan.

    Returns:
        Sorted paths of tracked files, excluding ``index.md`` itself.
    """
    return sorted(
        p
        for p in bundle.rglob("*")
        if p.is_file()
        and p.suffix in TRACKED_SUFFIXES
        and "__pycache__" not in p.parts
        and p.name != "index.md"
    )


def find_links(path: Path) -> list[tuple[int, str]]:
    """Extract resolvable markdown link targets from a file.

    Args:
        path: Markdown file to read.

    Returns:
        ``(line_number, target)`` pairs, with external and anchor-only links dropped
        and any trailing ``#anchor`` stripped.
    """
    found: list[tuple[int, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for target in LINK_RE.findall(line):
            if target.startswith(SKIP_LINK_PREFIXES):
                continue
            found.append((lineno, target.split("#", 1)[0]))
    return found


def check_links(files: list[Path], resolve_base: Path | None, label: str) -> tuple[int, list[str]]:
    """Check that every markdown link in ``files`` resolves.

    Args:
        files: Markdown files to scan.
        resolve_base: Directory links resolve against; ``None`` means each file's own directory.
        label: Name used in the progress line.

    Returns:
        ``(link_count, problems)`` where each problem is a ``file:line -> target`` string.
    """
    problems: list[str] = []
    count = 0
    for path in files:
        for lineno, target in find_links(path):
            if not target:
                continue
            count += 1
            base = resolve_base if resolve_base is not None else path.parent
            if not (base / target).exists():
                rel = path.relative_to(REPO_ROOT)
                problems.append(f"{rel}:{lineno} -> {target}")
    if problems:
        note(f"==> links       {label}: {count} links -> {len(problems)} unresolved")
    else:
        note(f"==> links       {label}: {count} links -> all resolve")
    return count, problems


def index_rows(index: Path) -> list[str]:
    """Return the backticked path from each ``index.md`` table row.

    Args:
        index: Path to ``index.md``.

    Returns:
        Paths as written in the first column, relative to the bundle root.
    """
    rows: list[str] = []
    for line in index.read_text(encoding="utf-8").splitlines():
        match = INDEX_ROW_RE.match(line)
        if match:
            rows.append(match.group(1))
    return rows


def check_index(bundle: Path) -> tuple[list[str], list[str]]:
    """Check ``index.md`` against the files on disk, in both directions.

    Args:
        bundle: Bundle directory.

    Returns:
        ``(uncovered, orphans)`` — files missing a row, and rows missing a file.
    """
    index = bundle / "index.md"
    if not index.exists():
        note(f"==> index       {index.relative_to(REPO_ROOT)} missing")
        return ["index.md is missing"], []

    rows = index_rows(index)
    on_disk = [str(p.relative_to(bundle)) for p in tracked_files(bundle)]

    uncovered = sorted(set(on_disk) - set(rows))
    orphans = sorted(row for row in rows if not (bundle / row).exists())

    total = len(on_disk)
    if uncovered:
        note(f"==> index       {total} files, {len(rows)} rows -> {len(uncovered)} uncovered")
    else:
        note(f"==> index       {total} files, {len(rows)} rows, index.md self-excluded -> covered")

    if orphans:
        note(f"==> orphans     {len(orphans)} rows name a missing file")
    else:
        note("==> orphans     none")

    return uncovered, orphans


def check_pointers(path: Path) -> list[str]:
    """Check that backticked ``agent_notes/...`` paths in a file exist.

    Args:
        path: File to scan, typically CLAUDE.md.

    Returns:
        ``file:line -> target`` strings for pointers that do not exist.
    """
    problems: list[str] = []
    count = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for target in BUNDLE_POINTER_RE.findall(line):
            count += 1
            if not (REPO_ROOT / target).exists():
                problems.append(f"{path.relative_to(REPO_ROOT)}:{lineno} -> {target}")
    rel = path.relative_to(REPO_ROOT)
    suffix = f"{len(problems)} missing" if problems else "all exist"
    note(f"==> pointers    {rel}: {count} backticked agent_notes/ paths -> {suffix}")
    return problems


def report(problems: list[str], header: str) -> None:
    """Print a problem list under a header, one entry per line.

    Args:
        problems: Problem strings to print.
        header: Section header.
    """
    if not problems:
        return
    print(f"\n--- {header} ---")
    for item in problems:
        print(f"    {item}")


def main() -> int:
    """Run every check and print a summary table.

    Returns:
        0 if all checks passed, 1 if any failed, 2 on bad usage.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "bundle",
        nargs="?",
        default=str(REPO_ROOT / "agent_notes"),
        help="bundle directory (default: agent_notes/)",
    )
    parser.add_argument(
        "--extra",
        action="append",
        default=None,
        help="extra file whose links and agent_notes/ pointers are checked (default: CLAUDE.md)",
    )
    parser.add_argument("--quiet", action="store_true", help="print problems only")
    args = parser.parse_args()

    bundle = Path(args.bundle)
    if not bundle.is_absolute():
        bundle = REPO_ROOT / bundle
    if not bundle.is_dir():
        print(f"error: not a directory: {bundle}", file=sys.stderr)
        return 2

    extra_args = args.extra if args.extra is not None else ["CLAUDE.md"]
    extras: list[Path] = []
    for name in extra_args:
        path = Path(name)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2
        extras.append(path)

    global QUIET
    QUIET = args.quiet

    _, link_problems = check_links(iter_markdown(bundle), None, f"{bundle.name}/")
    for extra in extras:
        _, extra_problems = check_links([extra], REPO_ROOT, str(extra.relative_to(REPO_ROOT)))
        link_problems += extra_problems

    uncovered, orphans = check_index(bundle)

    pointer_problems: list[str] = []
    for extra in extras:
        pointer_problems += check_pointers(extra)

    report(link_problems, "unresolved links")
    report(uncovered, "files missing from index.md")
    report(orphans, "index.md rows with no file")
    report(pointer_problems, "broken agent_notes/ pointers")

    results = [
        ("links", not link_problems),
        ("index", not uncovered),
        ("orphans", not orphans),
        ("pointers", not pointer_problems),
    ]
    note("\n==> Summary")
    for name, ok in results:
        note(f"    {name:<12} {'PASS' if ok else 'FAIL'}")

    return 0 if all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
