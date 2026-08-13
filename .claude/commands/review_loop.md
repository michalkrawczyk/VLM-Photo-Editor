---
description: "Loop batch reviews as subagents, tracked via TodoWrite, until all batches done"
argument-hint: "[--max-iterations N]"
---

Run:

/ralph-loop:ralph-loop "Each iteration: use TodoWrite to sync a checklist of the '## Batch N: <name>' headings in plans/plan_review.md against their [DONE] status (re-derive from the file, don't rely on prior context). Then launch one subagent via the Agent tool (subagent_type: general-purpose, foreground) with a self-contained prompt instructing it to invoke Skill batch_review to review the next batch not marked [DONE]. Wait for it to finish, then update the TodoWrite checklist. When plans/plan_review.md shows all batches [DONE], output: <promise>review is complete</promise>" --max-iterations ${1:-20} --completion-promise "review is complete"
