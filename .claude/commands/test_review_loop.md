---
description: "Test: loop /batch_review with /clear each iteration until all batches done"
argument-hint: "[--max-iterations N]"
---

```!
RALPH_SCRIPT="/home/tk/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/scripts/setup-ralph-loop.sh"
MAX="${1:-20}"
bash "$RALPH_SCRIPT" \
  --completion-promise "review is complete" \
  --max-iterations "$MAX" \
  "Each iteration: execute /clear to reset conversation context, then execute /batch_review. When batch_review finds all batches in plans/plan_review.md are marked [DONE] and reports the review is complete, output: <promise>review is complete</promise>"
```

Each iteration your task is:
1. Execute /clear to reset conversation context
2. Execute /batch_review to review the next pending batch
3. When all batches are done, output: <promise>review is complete</promise>
