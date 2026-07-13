# Product Description

Build a photo app that does four things well: edit backgrounds, frame photos, apply small corrections (exposure, white balance, denoise), and learn the user's editing style over time.

## Who It's For

A photographer or editor who wants fast, explainable, reversible edits — not a black box. They should always understand what the app intends to do, be able to change it in plain language, and trust that their originals and their API keys are safe.

## What "Good" Looks Like

These are the MVP's acceptance criteria — each bullet should be observably true in a live demo, not just directionally true.

- User sees a clear plan before anything happens and can steer it in chat until satisfied. Four accept modes control automation level: `manual` always prompts; `auto_low` skips approval when all ops are LOW risk; `auto_medium` skips approval when all ops are LOW or MEDIUM risk; `full_auto` executes immediately without any pre-execution human gate — including genAI ops, since subject-pixel-freeze and non-destructive saves mean a bad result only costs a rerun.
- Background edits look real, not pasted-in; the subject is never touched.
- Framing follows photographic intent (composition modes), not just an aspect ratio.
- Every edit is reversible, reproducible, and saved as a new file — the original is untouched.
- The app learns preferences (crop ratios, background style, correction intensity) from approved/edited plans, applied only after explicit opt-in, visible and resettable as a preference profile the user can inspect.
- When a plan step or genAI generation fails, the app surfaces the failure and asks how to proceed — it never silently drops a step or retries indefinitely. In batch mode this applies per-image: one failure doesn't block or roll back the rest of the batch.
- API keys are never exposed, logged, or stored in plaintext.

## Out of Scope

- Video or motion content — stills only.
- Multi-user / team collaboration or cloud sync — single local user per session.
- Mobile or web-hosted deployment — desktop Streamlit app only.
- Print production workflows (color-managed proofing, ICC-targeted output).
