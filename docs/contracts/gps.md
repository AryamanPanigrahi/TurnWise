# `POST /v1/gps` — GPS batch ingest (DRAFT)

The app sends fixes in batches (normally every 1–5 s; larger batches after an
offline period). Only while the driver is on duty **and** on a trip (DPDP).

## Request

```json
{
  "points": [
    {
      "trip_id": "trp_01HZX...",
      "ts": "2026-11-05T04:31:07.000Z",
      "lat": 12.97194,
      "lon": 77.59369,
      "speed": 8.3,
      "heading": 274.0,
      "accuracy": 6.5
    }
  ]
}
```

| Field | Type | Unit | Notes |
|---|---|---|---|
| `trip_id` | string | — | Must be an active trip assigned to the authenticated driver. |
| `ts` | string | UTC ISO-8601 | Device fix time, not send time. |
| `lat`, `lon` | number | WGS84 degrees | |
| `speed` | number \| null | m/s | null if unknown. |
| `heading` | number \| null | degrees, 0 = north, clockwise | null if unknown / stationary. |
| `accuracy` | number \| null | metres (68% radius) | |

- Max 600 points per batch (10 min at 1 Hz).
- Points may arrive out of order or duplicated after offline buffering; the
  server dedupes on `(trip_id, ts)` and sorts.

## Response

`202 Accepted`
```json
{ "accepted": 42, "duplicates": 0 }
```

Errors: `401` unauthenticated, `403` trip not assigned to driver / no consent,
`409` trip not active, `422` validation error.

## Open questions
- Auth: bearer JWT per driver device? (Aryaman)
- Compression (gzip) for offline backlog uploads?
