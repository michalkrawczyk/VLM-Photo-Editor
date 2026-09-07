# Product Description

Build a photo app that does four things well: edit backgrounds, frame photos, apply small corrections (exposure, white balance, denoise), and learn the user's editing style over time.

## Who It's For

A photographer or editor who wants fast, explainable, reversible edits — not a black box. They should always understand what the app intends to do, be able to change it in plain language, and trust that their originals and their API keys are safe.

## What "Good" Looks Like

These are the MVP's acceptance criteria — each bullet should be observably true in a live demo, not just directionally true.

- User sees a clear plan before anything happens and can steer it in chat until satisfied. Four accept modes control automation level: `manual` always prompts; `auto_low` skips approval when all ops are LOW risk; `auto_medium` skips approval when all ops are LOW or MEDIUM risk; `full_auto` executes immediately without any pre-execution human gate — including genAI ops, since subject-pixel-freeze and non-destructive saves mean a bad result only costs a rerun. `full_auto` is still bounded: a per-run ceiling on genAI generations / spend, and in batch a mandatory post-run review (accept / revert / re-plan per image) before any "Save All" — the freeze + non-destructive guarantees make a bad result cheap, not free.
- Background edits look real, not pasted-in; the subject is never touched.
- Framing follows photographic intent (composition modes), not just an aspect ratio — subject-aware framing depends on a subject-detection pre-pass (Character Focus, build plan P13); without it, crop anchoring falls back to image-centre.
- Every edit is reversible, reproducible, and saved as a new file — the original is untouched.
- The app learns preferences (crop ratios, background style, correction intensity) from approved/edited plans, applied only after explicit opt-in, visible and resettable as a preference profile the user can inspect.
- When a plan step or genAI generation fails, the app surfaces the failure and asks how to proceed — it never silently drops a step or retries indefinitely. In batch mode this applies per-image: one failure doesn't block or roll back the rest of the batch.
- API keys are never exposed, logged, or stored in plaintext.

## Out of Scope

- Video or motion content — stills only.
- Multi-user / team collaboration or cloud sync — single local user per session.
- Mobile or web-hosted deployment — desktop Streamlit app only.
- Print production workflows (color-managed proofing, ICC-targeted output).

## Deferred (Post-MVP)

- Input-safety guardrails — relevance / injection screening of user text (change requests, explicit preferences, framing instructions) before it reaches the planner or preference store. MVP threat model is a single local user; the prompt-injection / secret-exfiltration surface from the three free-text inputs is accepted and tracked. (Build plan P12.)
