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

## Dependencies

| Package | Area | Reason |
|---|---|---|
| PyYAML | voice | Parse `voice/templates/<lang>.yaml`; YAML is readable for non-programmer reviewers of translations. |
| pytest | tests | Standard Python test runner; replay and unit tests. |
