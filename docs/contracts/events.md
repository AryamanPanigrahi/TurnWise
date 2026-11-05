# `WS /v1/trips/{id}/events` — server-pushed trip events (DRAFT)

The app opens one WebSocket per active trip. The server pushes JSON messages.
Every message has an envelope:

```json
{ "event": "<type>", "trip_id": "trp_...", "ts": "2026-11-05T04:31:09.120Z", "seq": 17, "data": { } }
```

`seq` increases per trip so the client can detect gaps and drop duplicates.

## `off_route`
Emitted as soon as deviation is certain (target ≤ 2 s). Spoken with a
**templated** phrase — never through the AI model.

```json
"data": {
  "recovery": { "action": "u_turn", "distance_m": 300 },
  "deviation_m": 45,
  "confidence": 0.95
}
```
`recovery.action` ∈ `u_turn`, `turn_left`, `turn_right`, `continue`, `reroute`.

## `back_on_route`
```json
"data": {}
```

## `decision_point_ahead`
Pushed when a decision point is within the announce distance (e.g. 400 m and
again at 100 m). `data` is a fact card — see `fact_card.schema.json`.

## `arrived`
```json
"data": { "stop_id": "stp_...", "distance_m": 12 }
```

## Open questions
- Reconnect semantics: should the client send `last_seq` to replay missed events?
- Do we need a `heartbeat` event, or rely on WS ping/pong?
