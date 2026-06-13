# secrets — Agent Notes

**Role:** Resolve API keys from env → OS keyring → `.env`; scrub key-shaped strings from all log output.

## Import rules
- May import: stdlib (`logging`, `re`, `os`), `python-dotenv`, `keyring`
- Must NOT import: any other sibling module — secrets is a near-root dep; nothing in the pipeline should depend on it except `app/` and `models/`

## Critical invariants
- **Redaction filter wired at startup:** `RedactionFilter` is added to the root logger in `app/main.py` before any key ever flows through the system. Adding it later is too late.
- **Keys never leave `SecretStore`:** a resolved key must flow directly into the provider client constructor and nowhere else — no local variable that outlives the call, no logging, no session state.
- **UI shows last-4 only:** display helpers must mask all but the last 4 characters. Never show or log the full key.
- **Resolution precedence:** process env → OS keyring → gitignored `.env`. Never reverse this order.

## Files

| File | Responsibility |
|------|---------------|
| store.py | `SecretStore.get(provider)` — env → keyring → `.env` resolution |
| redaction.py | `RedactionFilter(logging.Filter)` — scrubs `sk-[A-Za-z0-9]{20,}` and similar patterns from all log records |

## Tests
- Location: `tests/unit/test_secrets.py`
- Key scenarios: `SecretStore` precedence order; key appears masked in UI helper; redaction filter removes key-shaped strings from log output; key is absent from all captured log records after a roundtrip

## Common mistakes

| Wrong | Correct |
|-------|---------|
| `logging.info(f"Using key: {key}")` | Never log a resolved key; log `"key resolved for {provider}"` only |
| Store resolved key in `st.session_state` | Pass key directly into provider client at call time |
| Add `RedactionFilter` after first VLM call | Wire it in `app/main.py` before anything else runs |
| Show full key in settings UI | Show `****{key[-4:]}` only |
