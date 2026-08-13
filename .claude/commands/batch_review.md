/goal In plans/plan_review.md, find the first batch not marked [DONE] 
and perform a code review for all files in that batch.

For each file, document findings in this order:
1. Principle & scope violations — read this project's own guiding docs
   (CLAUDE.md, README, goal/vision notes such as agent_notes/goal.md, or
   equivalent architecture docs at the repo root) and check the batch's
   files against whatever they state as non-negotiable: destructive-
   operation guarantees, secret/credential handling, approval or safety
   gates, data contracts between layers, stated in/out-of-scope
   boundaries. Flag any code path that contradicts a stated invariant —
   don't quietly bug-fix it or silently reinterpret the doc.
2. Bugs and correctness issues
3. Security or data-integrity risks
4. Code smells / maintainability
5. Performance optimizations
6. Over-engineered or unjustified functionality
7. Possible User Experience improvements (if applicable)

Merge the results to plans/issues.md. Give category 1 findings their own
"### Principle & Scope Violations" subheading per batch (same convention as
the existing "### Bugs & Correctness" / "### Security & Data Integrity"
subheadings), placed first, only when findings exist.

Insert the new "## Batch N Review" section immediately above the
"## Summary" heading — after the most recently added batch section, never
below Summary. Any explicit description of issues belongs before Summary.

Then append this batch's findings as rows into the single table under
"## Summary" (columns: `# | Severity | File | Issue`) and re-sort the full
table by severity (High → Medium → Low). Do not create a new table per
batch or per round — there is exactly one summary table. If a finding
restates an already-open row, cross-reference it (e.g. "(was PLN-B3)")
instead of adding a duplicate row.

When done, mark the batch in plan_review.md as [DONE] by appending 
it to the batch's ## heading. [DONE] means the review ran, not that the
batch is clean — open principle/scope violations stay in issues.md after
the batch is marked done.

If all batches are already marked [DONE], report that the review is complete.