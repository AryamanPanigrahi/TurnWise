# Interface contracts — DRAFT v0.1

These are the seams between Aryaman's side (engine/backend) and Ram's side
(voice/app/dashboard). **Change only together**: any PR touching this folder
needs approval from both founders.

| Contract | Producer | Consumer | File |
|---|---|---|---|
| `POST /v1/gps` | app | backend | [gps.md](gps.md) |
| `WS /v1/trips/{id}/events` | backend | app, voice | [events.md](events.md) |
| `POST /v1/ask` | backend | voice | [ask.md](ask.md) |
| Fact card | engine | backend, voice | [fact_card.schema.json](fact_card.schema.json) |

General rules:
- Units: metres, seconds, degrees. Timestamps are UTC ISO-8601 with `Z`.
- All endpoints are versioned under `/v1`. Breaking changes → `/v2`.
- Unknown fields must be ignored by consumers (forward compatibility).
