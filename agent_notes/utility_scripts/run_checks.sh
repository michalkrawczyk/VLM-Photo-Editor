#!/usr/bin/env bash
# Done Gate checks: lint, format, docstyle, tests. Runs every step, then reports.
#
#   run_checks.sh            fix mode: ruff --fix, black, isort, pydocstyle, fast tests
#   run_checks.sh --check    read-only: no file is modified
#   run_checks.sh --full     full pytest instead of -m "not slow"
#
# Exit 0 if every BLOCK step passed, 1 if any failed, 2 on bad usage.
# pydocstyle is advisory (WARN) and never fails the run. A missing tool is
# SKIP, never PASS — an uninstalled tool must not read as a green gate.

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 2

PKG="${PKG:-vlm_photo_editor}"   # pydocstyle target; override per project

CHECK_ONLY=0
FULL=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --full)  FULL=1 ;;
    *) echo "usage: $(basename "$0") [--check] [--full]" >&2; exit 2 ;;
  esac
done

[ -x .venv/bin/python ] && PATH="$REPO_ROOT/.venv/bin:$PATH"

STATUS=()
FAILED=0

# run <name> <severity: block|warn> <cmd...>
run() {
  local name=$1 severity=$2
  shift 2
  echo "==> $name: $*"
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "    not installed"
    STATUS+=("$name|SKIP")
    return
  fi
  if "$@"; then
    STATUS+=("$name|PASS")
  elif [ "$severity" = warn ]; then
    STATUS+=("$name|WARN")
  else
    STATUS+=("$name|FAIL")
    FAILED=1
  fi
}

if [ "$CHECK_ONLY" -eq 1 ]; then
  run ruff  block ruff check .
  run black block black --check .
  run isort block isort --check .
else
  run ruff  block ruff check --fix .
  run black block black .
  run isort block isort .
fi

run pydocstyle warn pydocstyle --convention=google "$PKG"

if [ "$FULL" -eq 1 ]; then
  run pytest block pytest
else
  run pytest block pytest -m "not slow"
fi

echo
echo "==> Summary"
for row in "${STATUS[@]}"; do
  printf '    %-12s %s\n' "${row%%|*}" "${row##*|}"
done

exit "$FAILED"
