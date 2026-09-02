#!/usr/bin/env bash
# Done Gate checks: lint, format, docstyle, tests. Runs every step, then reports.
#
#   run_checks.sh                        fix mode: ruff --fix, black, isort, pydocstyle, fast tests
#   run_checks.sh --check                read-only: no file is modified
#   run_checks.sh --full                 full pytest instead of -m "not slow" (unless -m/--marker given)
#   run_checks.sh [PATH ...]             pytest scope; default: tests/, else test/, else pytest's own discovery
#   run_checks.sh --short [N]            tail pytest output to last N lines (default 40); exit code still real
#   run_checks.sh -k|--match EXPR        pytest -k EXPR
#   run_checks.sh -m|--marker MARKER     override default "not slow" marker filter
#   run_checks.sh --ignore PATH          pytest --ignore PATH; repeatable
#
# Exit 0 if every BLOCK step passed, 1 if any failed, 2 on bad usage.
# pydocstyle is advisory (WARN) and never fails the run. A missing tool is
# SKIP, never PASS — an uninstalled tool must not read as a green gate.
# --short pipes pytest through tail; the real exit code is recovered via
# PIPESTATUS[0], not the pipe's own status. ruff/black/isort/pydocstyle are
# never piped — they stay on the shared run() path below.

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT" || exit 2

PKG="${PKG:-vlm_photo_editor}"   # pydocstyle target; override per project

usage() {
  echo "usage: $(basename "$0") [--check] [--full] [--short [N]] [-k|--match EXPR] [-m|--marker MARKER] [--ignore PATH]... [PATH ...]" >&2
  exit 2
}

CHECK_ONLY=0
FULL=0
SHORT=0
SHORT_LINES=40
MATCH_EXPR=""
MARKER=""
IGNORES=()
PYTEST_PATHS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1; shift ;;
    --full)  FULL=1; shift ;;
    --short=*)
      SHORT=1
      SHORT_LINES="${1#--short=}"
      shift
      ;;
    --short)
      SHORT=1
      if [[ "${2:-}" =~ ^[0-9]+$ ]]; then
        SHORT_LINES=$2
        shift 2
      else
        shift
      fi
      ;;
    -k|--match)
      [ $# -ge 2 ] || usage
      MATCH_EXPR=$2
      shift 2
      ;;
    -m|--marker)
      [ $# -ge 2 ] || usage
      MARKER=$2
      shift 2
      ;;
    --ignore)
      [ $# -ge 2 ] || usage
      IGNORES+=("$2")
      shift 2
      ;;
    -*) usage ;;
    *)
      PYTEST_PATHS+=("$1")
      shift
      ;;
  esac
done

[[ "$SHORT_LINES" =~ ^[0-9]+$ ]] || usage

if [ "${#PYTEST_PATHS[@]}" -eq 0 ]; then
  if [ -d tests ]; then
    PYTEST_PATHS=(tests)
  elif [ -d test ]; then
    PYTEST_PATHS=(test)
  fi
  # else: no conventional test dir found — leave empty, pytest falls back
  # to its own discovery/config (testpaths, rootdir, etc).
fi

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

PYTEST_ARGS=()
if [ "$FULL" -eq 1 ]; then
  [ -n "$MARKER" ] && PYTEST_ARGS+=(-m "$MARKER")
else
  PYTEST_ARGS+=(-m "${MARKER:-not slow}")
fi
[ -n "$MATCH_EXPR" ] && PYTEST_ARGS+=(-k "$MATCH_EXPR")
for ignore in "${IGNORES[@]}"; do
  PYTEST_ARGS+=(--ignore "$ignore")
done
PYTEST_ARGS+=("${PYTEST_PATHS[@]}")

# pytest gets its own block, not run(): --short needs a pipe to tail, and a
# piped command's exit status must be recovered from PIPESTATUS[0] — the
# other tools above are never piped, so they stay on the shared run() path.
echo "==> pytest: pytest ${PYTEST_ARGS[*]}"
if ! command -v pytest >/dev/null 2>&1; then
  echo "    not installed"
  STATUS+=("pytest|SKIP")
else
  if [ "$SHORT" -eq 1 ]; then
    pytest "${PYTEST_ARGS[@]}" 2>&1 | tail -n "$SHORT_LINES"
    PYTEST_EXIT=${PIPESTATUS[0]}
  else
    pytest "${PYTEST_ARGS[@]}"
    PYTEST_EXIT=$?
  fi
  if [ "$PYTEST_EXIT" -eq 0 ]; then
    STATUS+=("pytest|PASS")
  else
    STATUS+=("pytest|FAIL")
    FAILED=1
  fi
fi

echo
echo "==> Summary"
for row in "${STATUS[@]}"; do
  printf '    %-12s %s\n' "${row%%|*}" "${row##*|}"
done

exit "$FAILED"