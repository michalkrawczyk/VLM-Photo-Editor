#!/usr/bin/env bash
# End-of-session cleanup: format code and regenerate module map.

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "==> Running black..."
black vlm_photo_editor/ tests/

echo "==> Running isort..."
isort vlm_photo_editor/ tests/ --profile black

echo "==> Regenerating module map..."
python agent_notes/utility_scripts/generate_module_map.py

echo "==> Done."
