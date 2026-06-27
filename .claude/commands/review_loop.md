---
description: "Loop /batch_review with /compact each iteration until all batches done"
argument-hint: "[--max-iterations N]"
---

```!
RALPH_SCRIPT="/home/tk/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/scripts/setup-ralph-loop.sh"
MAX="${1:-20}"
bash "$RALPH_SCRIPT" \
  --completion-promise "review is complete" \
  --max-iterations "$MAX" \
  "Each iteration: run /compact with instruction 'Keep only: which batches in plans/plan_review.md are [DONE] and which remain. Drop all review findings and code details.', then run /batch_review. When batch_review finds all batches are [DONE] and reports the review is complete, output: <promise>review is complete</promise>"
```

Each iteration your task is:
1. Run /compact with instruction: "Keep only: which batches in plans/plan_review.md are [DONE] and which remain. Drop all review findings and code details."
2. Run /batch_review to review the next pending batch
3. When all batches are done, output: <promise>review is complete</promise>
