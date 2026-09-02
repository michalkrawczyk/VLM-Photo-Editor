/goal Split unstaged changes into a series of small, logical commits. If there are untracked files - ask user if should be also commited.

Rules:
- Group by logical unit: one feature/fix/refactor per commit. Split unrelated 
  hunks within the same file across separate commits if needed.
- Do not edit file contents — only stage and commit existing changes.
- Do not touch already-staged changes.
- Commit messages: conventional commits style (feat/fix/refactor/chore/docs/test), 
  imperative mood, concise summary (≤50 chars), optional body if non-obvious.
- Bundle generated/lockfile changes with the commit that caused them.
- Before committing, show the proposed commit plan (files/hunks + message) and 
  wait for confirmation.
- Do not push without user permission