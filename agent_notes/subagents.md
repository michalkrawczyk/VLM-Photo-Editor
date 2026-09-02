# Subagents

Delegate to keep main context clean and cheap. A subagent burns its own context and returns only its
report.

## Delegate when

- Search/exploration will read many files to yield a small answer (locate an implementation, map call
  sites, find which of 20 files matches)
- Reading bulk artifacts: logs, dumps, generated output, long docs, third-party source
- Independent verification: fresh eyes on a diff, reproducing a bug, checking a claim without
  inheriting your assumptions
- Two or more independent branches of work with no shared state
- Main context is filling and the remaining work needs room

## Never delegate

- Anything requiring the conversation's accumulated context — it does not transfer
- Small or known-path lookups: reading the file directly is cheaper than briefing an agent
- Write decisions, architecture choices, API design, tradeoff calls
- The Done Gate — the parent runs it, on its own machine, and owns the result
- Commits

## Brief format

The subagent has zero context. Omit nothing.

```
Goal: [one sentence, verifiable]
Scope: [paths in/out of bounds]
Method: module_map scripts first, then grep. Read-only unless stated.
Return: [exact shape — file:line list, table, yes/no + evidence]
Budget: [max files/steps]
```

`Method` matters here: this repo's search order is module-map-first (see [module_map.md](module_map.md)).
An agent left to its own devices will grep, which is slower and misses structure.

## Handling results

- A report is a claim, not a fact. Verify anything you act on — open the cited `file:line`.
- Unverifiable or vague return → rerun with a tighter `Return` spec. Don't guess.
- A subagent's "tests pass" never satisfies T1–T3. Rerun the gate yourself.
- Parallel agents → check for contradictions before merging. A contradiction is something to
  investigate, not average.

Report delegation in your summary: `Delegated: [what] → [what came back].`

See also: [module_map.md](module_map.md) · [done_gate.md](done_gate.md)
