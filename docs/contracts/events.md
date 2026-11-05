# WS /v1/trips/{id}/events  (DRAFT)

Server pushes JSON messages:

```json
{ "event": "off_route", "ts": "...", "recovery": "u-turn in 300 m" }
{ "event": "decision_point_ahead", "ts": "...", "fact_card": { } }
{ "event": "arrived", "ts": "..." }
```
`off_route` is produced by geometry/heading logic only — never by the AI model.
