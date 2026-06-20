"""Prompt template loader. Each .txt file in this directory is one named template."""

from pathlib import Path

_DIR = Path(__file__).parent


def load(name: str) -> str:
    """Return template text for `name`, or empty string if not found."""
    path = _DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def list_templates() -> list[str]:
    """Names of all available templates (stems of .txt files)."""
    return sorted(p.stem for p in _DIR.glob("*.txt"))
