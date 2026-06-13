# Goal

A photo app that edits backgrounds, frames photos, and applies small corrections. A VLM proposes a concise human-readable plan first; on accept, an executor compiles it into deterministic, validated operations. Background edits may use genAI; everything else uses Python imaging libs. Non-destructive throughout. Three accept modes (`AcceptMode` enum): `manual` — human approves every plan; `auto` — skips approval for all-LOW-risk op graphs; `full_auto` — executes immediately after compile, no human gate.
