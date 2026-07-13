---
description: Review goal.md for flaws, gaps, and improvement opportunities in the idea itself
allowed-tools: Read
---

/goal Review goal.md for flaws, gaps, and improvement opportunities in the idea itself

1. READ .agent_notes/goal.md fully. If .plans/steps.md exists, read it too 
   for context on what's already planned.

2. ANALYZE against these lenses. For each, note findings only if genuinely 
   present — don't force a finding per lens.
   - Problem validity: is the stated problem real/significant, or assumed?
   - User clarity: is the target user specific, or vague enough to mean anyone?
   - Value proposition: why this over existing alternatives — stated or missing?
   - Scope coherence: do Key Functionalities actually serve the Project Goal, 
     or has scope drifted/bloated beyond it?
   - Internal contradictions: any conflict between Key Functionalities, 
     User Perspective, and Out of Scope?
   - Feasibility flags: any functionality implying disproportionate complexity 
     vs. the stated goal (note only, don't estimate effort)?
   - Missing failure modes: what happens when things go wrong — errors, edge 
     users, misuse — is this acknowledged anywhere or silently assumed away?
   - Success criteria: is there any way to tell if the goal is achieved, 
     even implicitly?

3. CLASSIFY each finding as one of:
   - Flaw — actively wrong, contradictory, or will cause rework
   - Gap — missing but not contradictory
   - Opportunity — not broken, but a stronger version exists

4. OUTPUT a review, grouped by classification, each finding as:
   - one-line issue
   - one-line why it matters
   - one-line suggested fix (no code, no rewriting goal.md yourself)

5. Do NOT edit goal.md or steps.md. This is read-only review. If the user 
   wants fixes applied, they'll say so as a follow-up.

Constraints: no code snippets, no rewriting the files, group findings by 
severity within each classification (high/medium/low), max ~10 findings total 
— prioritize signal over completeness.