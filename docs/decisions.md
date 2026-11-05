# Decisions

Lightweight decision log (ADR-style). Newest at the bottom. Every new
dependency gets a one-line reason here (see CLAUDE.md → Conventions).

## Format

```
### NNNN — Title  (YYYY-MM-DD, owner, status: proposed | accepted | superseded)
Context / decision / consequences — a few lines.
```

---

### 0001 — Valhalla over OSRM for routing  (2026-11-05, Aryaman, status: proposed)
Valhalla exposes per-edge attributes (`bridge`, `tunnel`, `layer`, `highway=service`,
lanes) needed for flyover-vs-service-road fact cards. OSRM is faster but thinner.
Start with Valhalla; revisit if latency becomes a problem.

### 0002 — Interface contracts live in `docs/contracts/`  (2026-11-05, Ram, status: proposed)
Drafts for `POST /v1/gps`, `WS /v1/trips/{id}/events`, `POST /v1/ask` and the fact
card schema. Both founders must approve changes to any file in that folder.

### 0003 — Rule-based intent router before any AI model  (2026-11-05, Ram, status: proposed)
The 6 templated intents are matched with per-language keyword rules (pure Python,
no network). This keeps the templated path inside the 1.5 s budget and makes it
testable offline. Unmatched utterances go to the Sarvam LLM fallback (later).

### 0004 — Sarvam clients use stdlib urllib behind a Transport interface  (2026-11-05, Ram, status: proposed)
No HTTP dependency yet: the voice loop is synchronous push-to-talk, so urllib is
enough, and tests inject a fake transport (no network). If the backend needs
async calls from FastAPI, swap in an httpx transport — the interface stays.
Model names, endpoints and prices are overridable from `.env` (verified in 0006).

### 0005 — The AI model only classifies; templates always phrase  (2026-11-05, Ram, status: proposed)
CLAUDE.md lets the model phrase given facts. We go stricter: for unknown
questions the model only picks one of the 6 intent labels (validated against a
fixed list), and the answer is rendered from templates. The model can never
state a direction or distance, and prompt-injected speech cannot change the
answer. Revisit only if drivers ask many questions outside the 6 intents.

### 0006 — Sarvam models and prices checked against the docs  (2026-11-05, Ram, status: proposed)
Checked docs.sarvam.ai: `saarika:*` is deprecated (the API now accepts only
`saaras:v3`/`saaras:v4`), `sarvam-m` is no longer served, and `bulbul:v2` is legacy.
Defaults are now `saaras:v4`, `bulbul:v4-flash` (₹10 per 10k chars vs ₹30 for v3)
with per-language speakers, and `sarvam-105b` with reasoning turned off so the
one-word intent label fits in 20 tokens. TTS takes `language_code`, not
`target_language_code`. Prices are pay-as-you-go, excl. GST: STT ₹29.40/audio hour,
LLM ₹15 / ₹60 per 1M input / output tokens. Re-check before the first pilot.

### 0007 — Traces use the `POST /v1/gps` point shape  (2026-11-05, Ram, status: proposed)
Recorded drives are stored as `.jsonl`, one contract point per line, plus a
hand-written `.expected.json` with the events the engine should raise. Replay
tests then use the exact shape the app sends. `tools/gpx_to_trace.py` converts
GPSLogger exports (stdlib only) and trims 200 m off each end for privacy. The
expected-events format needs Aryaman's sign-off, since he owns the replay tests.

### 0010 — CI runs every test suite on each PR  (2026-11-05, Ram, status: proposed)
GitHub Actions (`.github/workflows/tests.yml`) runs pytest plus `tools.trace_check`,
the Kotlin `app/core` tests and the dashboard tests on every pull request, so a
reviewer sees green or red before reading the diff. Each job skips itself until
its folder exists. Ram's side also adopts the TurnWise name (package name, demo
banner, database names in `.env.example`); the contract schema `$id` is left for
both founders to change together.

## Dependencies

| Package | Area | Reason |
|---|---|---|
| PyYAML | voice | Parse `voice/templates/<lang>.yaml`; YAML is readable for non-programmer reviewers of translations. |
| pytest | tests | Standard Python test runner; replay and unit tests. |
| sounddevice (optional, not in pyproject) | voice demo | Microphone capture for the laptop push-to-talk demo only; the app records audio on Android. |
