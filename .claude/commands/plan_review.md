/goal Using only directory/structure navigation (no file content reading), 
create plans/plan_review.md that organizes the codebase into review batches.

Each batch should:
- Correspond to a natural logical unit (a module, a layer, or a 
  cross-cutting concern) — size follows structure, not a fixed file count
- Include a 2–3 sentence rationale: what groups these files and 
  what issues they're likely to contain

Structure the file as:
## Overview        — brief codebase summary from structure alone
## Batch N: <name> — file list, rationale, review focus

Review focus areas (in priority order):
1. Bugs and correctness issues
2. Security or data-integrity risks  
3. Code smells / maintainability
4. Performance optimizations
5. Over-engineered or unjustified functionality
6. Possible improvements for User Experiance/Interface