#!/bin/bash
set -euo pipefail

MAX=${1:-20}
cd "$(git rev-parse --show-toplevel)"

for ((i=1; i<=MAX; i++)); do
  if ! grep -qP '^## Batch(?!.*\[DONE\])' plans/plan_review.md; then
    echo "All batches done after $((i-1)) iterations."
    exit 0
  fi
  echo "=== Iteration $i / $MAX ==="
  claude -p "/batch_review"
done

echo "Reached max iterations ($MAX). Check plans/plan_review.md for remaining batches."
exit 1
